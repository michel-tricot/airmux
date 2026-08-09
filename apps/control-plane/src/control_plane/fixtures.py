"""A populated instance for frontend work, declared as the tables themselves.

Every entity below is a real model instance, so a renamed or retyped column fails ty before it can
fail against a database. That is the whole reason this is Python and not a YAML file parsed into a
second set of shapes: there is no parallel schema here to drift out of step with models/.

Nothing is minted. Ids come from uuid5 over a fixture namespace and secrets are constants, so a
bookmarked console URL, a saved login, and a token pasted into a .env survive being reseeded from
scratch. Seeding only ever runs against an empty database: to start over, drop it and recreate it.

The tokens here are public knowledge, which is what makes them useful and what makes them
unacceptable outside development. `airllmcp fixtures` refuses any database that already holds
accounts.

The file reads in three parts: every constant first, so the credentials and the knobs are in one
place; then the few helpers; then apply_fixtures, which is the instance itself, written top to
bottom and saved as it is declared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from random import Random
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.keys import INSTANCE_KEY_PREFIX, MANAGEMENT_KEY_PREFIX, key_prefix
from control_plane.models import (
    AuthIdentity,
    InferenceKey,
    InstanceKey,
    ManagementKey,
    Org,
    OrgMembership,
    UsageEvent,
    User,
    Workspace,
    WorkspaceMembership,
    set_actor,
)

if TYPE_CHECKING:
    from datetime import datetime

FIXTURE_NAMESPACE = UUID("cd85b596-7fd8-519f-9d36-7c5d39eea21f")

FIXTURE_PASSWORD = "password"  # noqa: S105 the shared development login, deliberately public

ACME_PROD_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-acme-production"
ACME_STAGING_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-acme-staging"
ACME_RETIRED_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-acme-retired"
SOLO_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-solo-default"
ACME_MANAGEMENT_TOKEN = f"{MANAGEMENT_KEY_PREFIX}fixture-acme"
INSTANCE_TOKEN = f"{INSTANCE_KEY_PREFIX}fixture-admin"

MODELS = [("gpt-4o-mini", "openai"), ("gpt-4o", "openai"), ("claude-opus-4-5", "anthropic")]

STATUSES = ["ok"] * 9 + ["error"]

USAGE_DAYS = 30


class NotAnEmptyDatabaseError(ValueError):
    """The target already holds accounts, so it is somebody's database rather than a fresh one.

    A ValueError so a caller can report it without importing this module for the type, the way the
    admin command already treats its own refusal.
    """


@dataclass(frozen=True)
class Fixtures:
    """How to get in: the shared password and the accounts it opens, then the tokens the API takes."""

    password: str
    admin_email: str
    emails: list[str]
    inference_token: str
    management_token: str
    instance_token: str


def fixture_id(name: str) -> UUID:
    """A stable id for a fixture entity, derived from its name rather than minted.

    The one deviation from the uuid7 rule the rest of the schema keeps, and it buys the property
    the seeder exists for: console URLs survive a reseed. Bundle is the existing precedent for a
    row passing its own id.
    """
    return uuid5(FIXTURE_NAMESPACE, name)


def inference_key(token: str, workspace: Workspace, user: User, *, label: str, revoked: bool = False) -> InferenceKey:
    """A key row for a token the fixtures already know, the way mint_inference_key builds one for a token it just drew."""
    return InferenceKey(
        id=fixture_id(f"inference-key:{workspace.name}:{label}"),
        org_id=workspace.org_id,
        workspace_id=workspace.id,
        user_id=user.id,
        token_hash=token_hash(token),
        prefix=key_prefix(token, INFERENCE_TOKEN_PREFIX),
        revoked=revoked,
        label=label,
    )


async def record_usage(workspace: Workspace, key: InferenceKey, count: int, now: datetime) -> None:
    """Recorded traffic for one workspace: random numbers spread over the last USAGE_DAYS.

    Nothing here reconciles. The costs are not the token counts times any price, because the
    console needs rows with a plausible shape, not an accounting identity.
    """
    rng = Random(f"usage:{workspace.id}")  # noqa: S311 fixture traffic, not cryptography
    for index in range(count):
        model_id, provider_id = rng.choice(MODELS)
        await UsageEvent(
            event_id=fixture_id(f"event:{workspace.id}:{index}"),
            request_id=fixture_id(f"request:{workspace.id}:{index}"),
            occurred_at=now - timedelta(seconds=rng.randint(0, USAGE_DAYS * 86400)),
            org_id=workspace.org_id,
            workspace_id=workspace.id,
            key_id=str(key.id),
            model_id=model_id,
            provider_id=provider_id,
            bundle_id=fixture_id(f"bundle:{workspace.org_id}"),
            input_tokens=rng.randint(300, 6000),
            output_tokens=rng.randint(80, 1500),
            cost_usd=rng.uniform(0.001, 0.5),
            cost_input_usd=rng.uniform(0.001, 0.2),
            cost_output_usd=rng.uniform(0.001, 0.3),
            cache_read_tokens=rng.choice([0, rng.randint(100, 3000)]),
            cache_write_tokens=0,
            latency_ms=rng.randint(180, 4000),
            status=rng.choice(STATUSES),
            stream=rng.choice([True, False]),
        ).save()


async def apply_fixtures(now: datetime) -> Fixtures:
    """The fixture instance, declared top to bottom and saved as it is declared.

    Read it as the list of what exists. Every row is written on the line that declares it, so there
    is no second pass to keep in step, and dependency order is ordinary data flow: nothing can name
    an org before the line that creates it.

    Seeds a fresh database only. There is no merge and no partial reset: to reseed, drop the
    database and recreate it. That keeps this a straight line of inserts, and keeps the seeder from
    ever deciding which of somebody's rows it is entitled to delete.

    now is injected the way the compiler injects it: the seeder stays a function of its inputs, so
    a test can pin the clock and get the same series every run.
    """
    if await User.first() is not None:
        msg = "this is not an empty database; fixtures seed a fresh one, so drop and recreate it first"
        raise NotAnEmptyDatabaseError(msg)

    await set_actor("root")

    michel = await User(id=fixture_id("user:michel"), email="m@airbyte.com", name="Michel Tricot", instance_admin=True).save()
    await AuthIdentity.set_password(michel, FIXTURE_PASSWORD)

    dana = await User(id=fixture_id("user:dana"), email="b@airbyte.com", name="Dana Reeves").save()
    await AuthIdentity.set_password(dana, FIXTURE_PASSWORD)

    acme = await Org(id=fixture_id("org:acme"), name="Acme", personal_for=michel.id).save()
    solo = await Org(id=fixture_id("org:solo"), name="Solo Shop").save()

    await OrgMembership(user_id=michel.id, org_id=acme.id).save()
    await OrgMembership(user_id=dana.id, org_id=acme.id).save()
    await OrgMembership(user_id=dana.id, org_id=solo.id).save()

    production = await Workspace(id=fixture_id("workspace:acme:production"), org_id=acme.id, name="production").save()
    staging = await Workspace(id=fixture_id("workspace:acme:staging"), org_id=acme.id, name="staging").save()
    default = await Workspace(id=fixture_id("workspace:solo:default"), org_id=solo.id, name="default").save()

    await WorkspaceMembership(user_id=michel.id, workspace_id=production.id, org_id=acme.id).save()
    await WorkspaceMembership(user_id=dana.id, workspace_id=production.id, org_id=acme.id).save()
    await WorkspaceMembership(user_id=michel.id, workspace_id=staging.id, org_id=acme.id).save()
    await WorkspaceMembership(user_id=dana.id, workspace_id=default.id, org_id=solo.id).save()

    checkout = await inference_key(ACME_PROD_TOKEN, production, michel, label="checkout-service").save()
    ci = await inference_key(ACME_STAGING_TOKEN, staging, michel, label="ci").save()
    solo_key = await inference_key(SOLO_TOKEN, default, dana, label="default").save()
    await inference_key(ACME_RETIRED_TOKEN, production, dana, label="batch-jobs", revoked=True).save()

    await ManagementKey(
        id=fixture_id("management-key:acme"),
        org_id=acme.id,
        user_id=michel.id,
        token_hash=token_hash(ACME_MANAGEMENT_TOKEN),
        prefix=key_prefix(ACME_MANAGEMENT_TOKEN, MANAGEMENT_KEY_PREFIX),
        label="fixture-cli",
    ).save()
    await InstanceKey(
        id=fixture_id("instance-key:admin"),
        user_id=michel.id,
        token_hash=token_hash(INSTANCE_TOKEN),
        prefix=key_prefix(INSTANCE_TOKEN, INSTANCE_KEY_PREFIX),
        label="fixture-admin",
    ).save()

    await record_usage(production, checkout, 1200, now)
    await record_usage(staging, ci, 360, now)
    await record_usage(default, solo_key, 84, now)

    return Fixtures(
        password=FIXTURE_PASSWORD,
        admin_email=michel.email,
        emails=[michel.email, dana.email],
        inference_token=ACME_PROD_TOKEN,
        management_token=ACME_MANAGEMENT_TOKEN,
        instance_token=INSTANCE_TOKEN,
    )
