from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values, set_key, unset_key
from pydantic import BaseModel
from sqlmodel import col

from contract import private_key_from_b64, private_key_to_b64, public_key_to_b64, verify_inference_token
from control_plane.compiler import compile_and_store
from control_plane.db import current_actor
from control_plane.deps import claims_are_backed
from control_plane.models import ApiKey, Bundle, Org, OrgMembership, User
from control_plane.tokens import mint_caller_key, mint_mgmt, verify_management_token

if TYPE_CHECKING:
    from pathlib import Path

    from control_plane.config import Settings

DEFAULT_CONFIG_YML = """control_plane:
  database:
    url: {db_url}
  auth:
    token_signing_key: env:GW_TOKEN_SIGNING_KEY
  bundle:
    signing_key: env:GW_BUNDLE_SIGNING_KEY
    staleness_bound_hours: 24

data_plane:
  control_plane:
    url: {control_plane_url}
    token: env:GW_DATAPLANE_TOKEN
  bundle:
    public_key: env:GW_BUNDLE_PUBLIC_KEY
    org: {org}
    cache_dir: {cache_dir}
    staleness_policy: serve_and_warn # or refuse
    poll_interval_s: 5
  auth:
    token_public_key: env:GW_TOKEN_PUBLIC_KEY
  events:
    flush_interval_s: 5
"""

_SIGNING_KEYS = (("GW_BUNDLE_SIGNING_KEY", "GW_BUNDLE_PUBLIC_KEY"), ("GW_TOKEN_SIGNING_KEY", "GW_TOKEN_PUBLIC_KEY"))
_STALE_ENV_KEYS = (
    "GW_CONTROL_PLANE_URL",
    "GW_CACHE_DIR",
    "GW_POLL_INTERVAL_S",
    "GW_SIGNING_KEY",
    "GW_ADMIN_TOKEN",
    "GW_MGMT_TOKEN",
    "GW_ORG_TOKEN",
    "GW_DP_TOKEN",
)


def ensure_signing_keys(env_path: Path) -> tuple[list[str], list[str]]:
    """Generate or reuse the two Ed25519 key pairs; returns the (generated, reused) private-key env names."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.touch(exist_ok=True)
    existing = dotenv_values(env_path)
    generated: list[str] = []
    reused: list[str] = []
    for private_name, public_name in _SIGNING_KEYS:
        stored = existing.get(private_name)
        key = private_key_from_b64(stored) if stored else Ed25519PrivateKey.generate()
        (reused if stored else generated).append(private_name)
        set_key(env_path, private_name, private_key_to_b64(key))
        set_key(env_path, public_name, public_key_to_b64(key.public_key()))
    for stale in _STALE_ENV_KEYS:
        if stale in existing:
            unset_key(env_path, stale)
    return generated, reused


class NotAnAdminError(Exception):
    """The email belongs to an existing user that is not a human instance admin."""


class AdminToken(BaseModel):
    user_id: str
    email: str
    token_id: str
    token: str
    created: bool


async def create_admin(settings: Settings, email: str, name: str = "", *, if_missing: bool = False) -> AdminToken | None:
    """Create an instance admin and mint their instance-scoped token, both audited as that user.

    An existing admin just gets a fresh token: this is the break-glass path for lost credentials,
    and whoever can run this against the database is already the operator, so there is no run-once
    guard. if_missing turns the existing-admin case into a no-op so scripted setups never churn
    tokens. Runs inside the caller's transaction; the CLI entry point opens its own.
    """
    user = await User.first(User.email == email)
    if user is not None and (user.service_account or not user.instance_admin):
        raise NotAnAdminError(email)
    if user is not None and if_missing:
        return None
    created = user is None
    if user is None:
        user = User(id=f"u-{uuid4().hex[:8]}", email=email, name=name or email, instance_admin=True, service_account=False)
    current_actor.set(user.id)
    if created:
        await user.save()
    private_key = private_key_from_b64(settings.auth.token_signing_key)
    token_id, token = await mint_mgmt(None, private_key, datetime.now(tz=UTC), user.id)
    return AdminToken(user_id=user.id, email=email, token_id=token_id, token=token, created=created)


async def find_admin() -> User | None:
    return await User.first(col(User.instance_admin).is_(True), col(User.service_account).is_(False), order_by=col(User.created_at))


def org_name_from_email(email: str) -> str:
    """Pretty org display name from the email domain, e.g. michel@acme-corp.io -> Acme Corp.

    The domain must have a name and an extension; anything else falls back to My Organization.
    """
    domain = email.rpartition("@")[2]
    labels = [label for label in domain.split(".") if label]
    name_and_extension = 2
    if len(labels) < name_and_extension:
        return "My Organization"
    words = [word for label in labels[:-1] for word in re.split(r"[-_]+", label) if word]
    return " ".join(word.capitalize() for word in words) or "My Organization"


async def _mgmt_token_is_live(settings: Settings, token: str | None, org_id: str | None, expected_user: str | None = None) -> bool:
    """A stored env token is kept only if the current signing key verifies it and its claims still hold in this database.

    The env file and the database can drift apart (a recreated database orphans the users old
    tokens are bound to, and the control plane 401s those), so presence in the env file alone is
    never proof of validity.
    """
    claims = verify_management_token(token, private_key_from_b64(settings.auth.token_signing_key).public_key()) if token else None
    if claims is None or claims.org_id != org_id or (expected_user is not None and claims.user_id != expected_user):
        return False
    return await claims_are_backed(claims)


async def _caller_token_is_live(settings: Settings, token: str | None, org_id: str) -> bool:
    if not token:
        return False
    claims = verify_inference_token(token, private_key_from_b64(settings.auth.token_signing_key).public_key())
    if claims is None or claims.org_id != org_id:
        return False
    key = await ApiKey.get(claims.key_id)
    return key is not None and not key.disabled


async def ensure_admin(settings: Settings, email: str, name: str, env_path: Path) -> str:
    """Idempotent admin step for init: create the admin if missing, mint GW_ADMIN_MGMT_TOKEN unless the stored one is still live."""
    user = await User.first(User.email == email)
    if user is not None and await _mgmt_token_is_live(settings, dotenv_values(env_path).get("GW_ADMIN_MGMT_TOKEN"), None, expected_user=user.id):
        if user.service_account or not user.instance_admin:
            raise NotAnAdminError(email)
        current_actor.set(user.id)
        return f"instance admin {user.id} ({email}) exists, GW_ADMIN_MGMT_TOKEN kept"
    minted = await create_admin(settings, email, name)
    assert minted is not None  # noqa: S101 if_missing is False so create_admin always mints
    set_key(env_path, "GW_ADMIN_MGMT_TOKEN", minted.token)
    verb = "created instance admin" if minted.created else "re-minted GW_ADMIN_MGMT_TOKEN for instance admin"
    return f"{verb} {minted.user_id} ({email})"


async def _ensure_service_account(org_id: str) -> User:
    for membership in await OrgMembership.find(OrgMembership.org_id == org_id):
        user = await User.get(membership.user_id)
        if user is not None and user.service_account:
            return user
    sa = await User.new_service_account("data-plane").save()
    await OrgMembership(user_id=sa.id, org_id=org_id).save()
    return sa


async def ensure_org(settings: Settings, org_id: str, env_path: Path, *, skip_key: bool = False) -> str:
    """Idempotent org step for init: org, data-plane service account, and whichever org-scoped tokens the env file is missing.

    GW_ORG_MGMT_TOKEN binds to the earliest instance admin when one exists, GW_DATAPLANE_TOKEN to the service
    account, AIRLLM_TOKEN to a fresh wildcard API key unless skip_key.
    """
    admin = await find_admin()
    created = await Org.get(org_id) is None
    if created:
        await Org(id=org_id, name=org_name_from_email(admin.email) if admin else "My Organization").save()
    sa = await _ensure_service_account(org_id)
    env = dotenv_values(env_path)
    now = datetime.now(tz=UTC)
    private_key = private_key_from_b64(settings.auth.token_signing_key)
    minted: dict[str, str] = {}
    for env_name, owner in (("GW_ORG_MGMT_TOKEN", admin.id if admin else None), ("GW_DATAPLANE_TOKEN", sa.id)):
        if await _mgmt_token_is_live(settings, env.get(env_name), org_id):
            continue
        _, minted[env_name] = await mint_mgmt(org_id, private_key, now, owner)
    if not skip_key and not await _caller_token_is_live(settings, env.get("AIRLLM_TOKEN"), org_id):
        _, minted["AIRLLM_TOKEN"] = await mint_caller_key(org_id, ["*"], private_key, now)
    for env_name, token in minted.items():
        set_key(env_path, env_name, token)
    state = "created" if created else "exists"
    tokens_part = f"minted {', '.join(minted)}" if minted else "all tokens present"
    return f"org {org_id} {state}, service account {sa.id}, {tokens_part}"


async def ensure_bundle(settings: Settings, org_id: str) -> str:
    """Compile bundle v1 if the org has none; taxonomy edits recompile through `control-plane taxonomy`."""
    latest = await Bundle.first(Bundle.org_id == org_id, order_by=col(Bundle.version).desc())
    if latest is not None:
        return f"bundle v{latest.version} current, run `control-plane taxonomy` after taxonomy edits"
    version = await compile_and_store(org_id, uuid4(), datetime.now(tz=UTC), settings.bundle.staleness_bound, settings.bundle.signing_key)
    return f"compiled bundle v{version}"
