from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import dotenv_values, set_key
from pydantic import BaseModel
from sqlmodel import col

from contract import INFERENCE_TOKEN_PREFIX, private_key_from_b64, private_key_to_b64, public_key_to_b64, token_hash
from control_plane.compiler import compile_and_store
from control_plane.db import current_actor
from control_plane.models import ApiKey, Bundle, Org, OrgMembership, User
from control_plane.tokens import mint_inference_key, mint_mgmt_key, verify_management_token

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from control_plane.config import Settings

_SIGNING_KEYS = (("GW_BUNDLE_SIGNING_KEY", "GW_BUNDLE_PUBLIC_KEY"),)
ADMIN_TOKEN_ENV = "GW_ADMIN_MGMT_TOKEN"  # noqa: S105 env var name, not a secret


def ensure_signing_keys(env_path: Path) -> tuple[list[str], list[str]]:
    """Generate or reuse the Ed25519 bundle key pair; returns the (generated, reused) private-key env names."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.touch(exist_ok=True)
    existing = dotenv_values(env_path)
    generated: list[str] = []
    reused: list[str] = []
    for private_name, public_name in _SIGNING_KEYS:
        stored = existing.get(private_name)
        key = private_key_from_b64(stored) if stored else Ed25519PrivateKey.generate()
        (reused if stored else generated).append(private_name)
        for name, value in ((private_name, private_key_to_b64(key)), (public_name, public_key_to_b64(key.public_key()))):
            if existing.get(name) != value:
                set_key(env_path, name, value)
    return generated, reused


class NotAnAdminError(Exception):
    """The email belongs to an existing user that is not a human instance admin."""


class AdminToken(BaseModel):
    user_id: str
    token_id: str
    token: str
    created: bool


async def create_admin(email: str, name: str = "", *, if_missing: bool = False) -> AdminToken | None:
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
    token_id, token = await mint_mgmt_key(None, user.id)
    return AdminToken(user_id=user.id, token_id=token_id, token=token, created=created)


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


async def _mgmt_token_is_live(token: str | None, org_id: str | None, expected_user: str | None = None) -> bool:
    """A stored env token is kept only if this database still backs it.

    The env file and the database can drift apart (a recreated database orphans the users old
    tokens are bound to, and the control plane 401s those), so presence in the env file alone is
    never proof of validity.
    """
    claims = await verify_management_token(token) if token else None
    return claims is not None and claims.org_id == org_id and (expected_user is None or claims.user_id == expected_user)


async def _caller_token_is_live(token: str | None, org_id: str) -> bool:
    if not token or not token.startswith(INFERENCE_TOKEN_PREFIX):
        return False
    key = await ApiKey.first(ApiKey.token_hash == token_hash(token))
    return key is not None and key.org_id == org_id and not key.disabled


async def ensure_admin(email: str, name: str, env: Mapping[str, str | None]) -> tuple[str, dict[str, str]]:
    """Idempotent admin step for init: create the admin if missing, mint GW_ADMIN_MGMT_TOKEN unless the stored one is still live.

    Returns the step message and the tokens to write to the env file; the caller writes them after
    the transaction commits so the env file never holds tokens whose rows were rolled back.
    """
    user = await User.first(User.email == email)
    if user is not None and (user.service_account or not user.instance_admin):
        raise NotAnAdminError(email)
    if user is not None and await _mgmt_token_is_live(env.get(ADMIN_TOKEN_ENV), None, expected_user=user.id):
        current_actor.set(user.id)
        return f"instance admin {user.id} ({email}) exists, {ADMIN_TOKEN_ENV} kept", {}
    minted = await create_admin(email, name)
    assert minted is not None  # noqa: S101 if_missing is False so create_admin always mints
    verb = "created instance admin" if minted.created else f"re-minted {ADMIN_TOKEN_ENV} for instance admin"
    return f"{verb} {minted.user_id} ({email})", {ADMIN_TOKEN_ENV: minted.token}


async def _ensure_service_account(org_id: str) -> User:
    for membership in await OrgMembership.find(OrgMembership.org_id == org_id):
        user = await User.get(membership.user_id)
        if user is not None and user.service_account:
            return user
    sa = await User.new_service_account("data-plane").save()
    await OrgMembership(user_id=sa.id, org_id=org_id).save()
    return sa


async def ensure_org(org_id: str, env: Mapping[str, str | None], *, skip_key: bool = False) -> tuple[str, dict[str, str]]:
    """Idempotent org step for init: org, data-plane service account, and whichever org-scoped tokens the env file is missing.

    GW_ORG_MGMT_TOKEN binds to the earliest instance admin when one exists (the service account
    otherwise), GW_DATAPLANE_TOKEN to the service account, AIRLLM_TOKEN to a fresh API key unless
    skip_key. Returns the step message and the tokens to write to the env file; the caller writes
    them after the transaction commits.
    """
    admin = await find_admin()
    created = await Org.get(org_id) is None
    if created:
        await Org(id=org_id, name=org_name_from_email(admin.email) if admin else "My Organization").save()
    sa = await _ensure_service_account(org_id)
    minted: dict[str, str] = {}
    for env_name, owner in (("GW_ORG_MGMT_TOKEN", admin.id if admin else sa.id), ("GW_DATAPLANE_TOKEN", sa.id)):
        if await _mgmt_token_is_live(env.get(env_name), org_id):
            continue
        _, minted[env_name] = await mint_mgmt_key(org_id, owner)
    if not skip_key and not await _caller_token_is_live(env.get("AIRLLM_TOKEN"), org_id):
        _, minted["AIRLLM_TOKEN"] = await mint_inference_key(org_id, sa.id)
    state = "created" if created else "exists"
    tokens_part = f"minted {', '.join(minted)}" if minted else "all tokens present"
    return f"org {org_id} {state}, service account {sa.id}, {tokens_part}", minted


async def ensure_bundle(settings: Settings, org_id: str) -> str:
    """Compile bundle v1 if the org has none; taxonomy edits recompile through `airllmcp taxonomy`."""
    latest = await Bundle.first(Bundle.org_id == org_id, order_by=col(Bundle.version).desc())
    if latest is not None:
        return f"bundle v{latest.version} current, run `airllmcp taxonomy` after taxonomy edits"
    version = await compile_and_store(org_id, uuid4(), datetime.now(tz=UTC), settings.bundle.staleness_bound, settings.bundle.signing_key)
    return f"compiled bundle v{version}"
