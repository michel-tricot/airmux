"""A populated instance for frontend work, declared as the tables themselves.

Every entity below is a real model instance, so a renamed or retyped column fails ty before it can
fail against a database. That is the whole reason this is Python and not a YAML file parsed into a
second set of shapes: there is no parallel schema here to drift out of step with models/.

Nothing is minted. Ids come from uuid5 over a fixture namespace and secrets are constants, so a
bookmarked console URL, a saved login, and a token pasted into a .env survive being reseeded from
scratch. Seeding only runs before any human account exists: to start over, drop the database and recreate it.

The tokens here are public knowledge, which is what makes them useful and what makes them
unacceptable outside development. `airllmcp fixtures` refuses any database that already holds
human accounts.

The file reads in three parts: every constant first, so the credentials and the knobs are in one
place; then the few helpers; then apply_fixtures, which is the instance itself, written top to
bottom and saved as it is declared.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from random import Random
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

from sqlmodel import col

from contract import INFERENCE_TOKEN_PREFIX, Secret, SecretRejectedError, SecretStore, UsageStatus, token_hash
from contract.policies import (
    AllKeys,
    AllowedModels,
    AllowedProviders,
    AllRequests,
    Budget,
    CredentialAccess,
    DenyRequest,
    Fallback,
    PolicyAction,
    PolicyDefinition,
    PriceLimit,
    RequestLimits,
    RequestMatch,
    RuleDefinition,
    SelectedKeys,
    StrictParameters,
)
from control_plane.authz import ALL_PERMISSIONS, OrgRole, WorkspaceRole, permissions_for_org_role
from control_plane.keys import MANAGEMENT_KEY_PREFIX, key_prefix
from control_plane.models import (
    AuthIdentity,
    DataPlaneInstance,
    InferenceKey,
    ManagementKey,
    Model,
    Org,
    OrgInvitation,
    OrgMembership,
    Policy,
    Provider,
    ProviderCredential,
    Rule,
    UsageEvent,
    User,
    Workspace,
    WorkspaceMembership,
    set_actor,
)
from control_plane.models.org_invitation import INVITATION_TOKEN_PREFIX
from control_plane.passwords import hash_password

if TYPE_CHECKING:
    from datetime import datetime

    from control_plane.models.provider_credential import ProviderCredentialStatus

FIXTURE_NAMESPACE = UUID("cd85b596-7fd8-519f-9d36-7c5d39eea21f")

FIXTURE_PASSWORD = "password"  # noqa: S105 the shared development login, deliberately public

ACME_PROD_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-acme-production"
ACME_STAGING_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-acme-staging"
ACME_RETIRED_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-acme-retired"
SOLO_TOKEN = f"{INFERENCE_TOKEN_PREFIX}fixture-solo-default"
ACME_ACCESS_TOKEN = f"{MANAGEMENT_KEY_PREFIX}fixture-acme"
INSTANCE_ACCESS_TOKEN = f"{MANAGEMENT_KEY_PREFIX}fixture-admin"
ACME_MEMBER_INVITE_TOKEN = f"{INVITATION_TOKEN_PREFIX}fixture-acme-member"
ACME_PRODUCTION_INVITE_TOKEN = f"{INVITATION_TOKEN_PREFIX}fixture-acme-production-viewer"
ACME_EXPIRED_INVITE_TOKEN = f"{INVITATION_TOKEN_PREFIX}fixture-acme-expired"

OPENAI_GPT_4O_MINI = "openai/gpt-4o-mini"
OPENAI_GPT_4O = "openai/gpt-4o"
ANTHROPIC_CLAUDE_OPUS = "anthropic/claude-opus-4-5-20251101"

MODELS = [(OPENAI_GPT_4O_MINI, "openai"), (OPENAI_GPT_4O, "openai"), (ANTHROPIC_CLAUDE_OPUS, "anthropic")]

ROUTED_PROVIDERS = sorted({provider for _, provider in MODELS})
"""The providers the fixture traffic and credentials name. Taxonomy owns whether they exist; these
are looked up, never created, so a fixture instance cannot drift from the catalog an operator has."""

FIXTURE_PROVIDER_KEY = "sk-fixture-not-a-real-key-0000"

ROUTED_MODELS = sorted({model for model, _ in MODELS})


STATUSES: tuple[UsageStatus, ...] = (*("ok",) * 9, "upstream_error")

USAGE_DAYS = 30


class MissingProvidersError(ValueError):
    """The catalog does not hold the providers the fixtures route to.

    Seeding around the gap would produce usage rows and credentials naming providers nothing routes
    to: an instance that looks populated and serves nothing. A ValueError for the same reason the
    empty-database refusal is one, so the command reports it without importing this module.
    """

    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"the catalog has no {', '.join(missing)}; run `airllmcp taxonomy` to fill it before seeding")


class MissingModelsError(ValueError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"the catalog has no {', '.join(missing)}; run `airllmcp taxonomy` to fill it before seeding")


class ExistingHumanAccountsError(ValueError):
    """The target already holds human accounts, so it is somebody's database rather than a fresh one.

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
    org_access_token: str
    instance_access_token: str
    invitation_tokens: list[tuple[str, str]]
    unresolved_providers: list[str]  # seeded credentials whose store holds no value, so nothing routes through them yet


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


async def provider_credential(  # noqa: PLR0913 the row's own fields are the arguments
    store: SecretStore,
    provider: Provider,
    org: Org,
    *,
    workspace: Workspace | None = None,
    name: str = "default",
    priority: int = 100,
    status: ProviderCredentialStatus = "unknown",
    enabled: bool = True,
) -> ProviderCredential:
    """A credential row, and the value behind it when the store can hold one."""
    credential = await ProviderCredential(
        id=fixture_id(f"provider-credential:{org.name}:{workspace.name if workspace else 'org'}:{provider.name}:{name}"),
        org_id=org.id,
        workspace_id=workspace.id if workspace else None,
        provider_id=provider.id,
        provider_name=provider.name,
        name=name,
        priority=priority,
        enabled=enabled,
        status=status,
    ).save()
    with contextlib.suppress(SecretRejectedError):
        credential.fingerprint = (await store.put(credential.secret_ref(), Secret(FIXTURE_PROVIDER_KEY))).fingerprint
    return await credential.save()


async def workspace_policy(  # noqa: PLR0913 target and rule references stay explicit in fixture call sites
    workspace: Workspace,
    *,
    name: str,
    priority: int,
    target: AllKeys | SelectedKeys,
    rules: tuple[Rule, ...],
    enabled: bool = True,
) -> Policy:
    return await Policy(
        id=fixture_id(f"policy:{workspace.name}:{name}"),
        org_id=workspace.org_id,
        workspace_id=workspace.id,
        name=name,
        enabled=enabled,
        priority=priority,
        definition=PolicyDefinition(target=target, rule_ids=tuple(rule.id for rule in rules)),
    ).save()


async def workspace_rule(workspace: Workspace, *, name: str, match: AllRequests | RequestMatch, action: PolicyAction) -> Rule:
    return await Rule(
        id=fixture_id(f"rule:{workspace.name}:{name}"),
        org_id=workspace.org_id,
        workspace_id=workspace.id,
        name=name,
        definition=RuleDefinition.model_validate({"match": match, "action": action}),
    ).save()


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


async def apply_fixtures(now: datetime, store: SecretStore) -> Fixtures:  # noqa: PLR0915 fixture graph stays readable as one declared instance
    """The fixture instance, declared top to bottom and saved as it is declared.

    Provider credentials are the one part whose value lives outside the database. The rows are
    always written; whether a value is written beside them is the store's business, and on the env
    store the answer is that the ref already resolves to a variable the operator owns.

    The catalog is a precondition rather than something seeded here: taxonomy owns which providers
    exist, so this reads them and refuses when the ones its traffic names are absent.

    Read it as the list of what exists. Every row is written on the line that declares it, so there
    is no second pass to keep in step, and dependency order is ordinary data flow: nothing can name
    an org before the line that creates it.

    Seeds a database with no human accounts. Deployment service accounts may already exist because
    the control plane creates them before becoming healthy. There is no merge and no partial reset:
    to reseed, drop the database and recreate it. That keeps this a straight line of inserts, and
    keeps the seeder from ever deciding which of somebody's rows it is entitled to delete.

    now is injected the way the compiler injects it: the seeder stays a function of its inputs, so
    a test can pin the clock and get the same series every run.
    """
    if await User.first(col(User.service_account).is_(False)) is not None:
        msg = "this database already has human accounts; fixtures seed a fresh instance, so drop and recreate it first"
        raise ExistingHumanAccountsError(msg)

    catalog = {provider.name: provider for provider in await Provider.find(col(Provider.name).in_(ROUTED_PROVIDERS))}
    if missing := [name for name in ROUTED_PROVIDERS if name not in catalog]:
        raise MissingProvidersError(missing)
    catalog_models = {model.name for model in await Model.find(col(Model.name).in_(ROUTED_MODELS))}
    if missing := [name for name in ROUTED_MODELS if name not in catalog_models]:
        raise MissingModelsError(missing)

    await set_actor("root")

    michel = await User(id=fixture_id("user:michel"), email="m@airbyte.com", name="Michel Tricot", instance_role="owner").save()
    await AuthIdentity.set_password_hash(michel, hash_password(FIXTURE_PASSWORD))

    dana = await User(id=fixture_id("user:dana"), email="b@airbyte.com", name="Dana Reeves").save()
    await AuthIdentity.set_password_hash(dana, hash_password(FIXTURE_PASSWORD))

    acme = await Org(id=fixture_id("org:acme"), name="Acme", slug="acme", personal_for=michel.id).save()
    solo = await Org(id=fixture_id("org:solo"), name="Solo Shop", slug="solo-shop").save()

    await OrgMembership(user_id=michel.id, org_id=acme.id, role=OrgRole.owner).save()
    await OrgMembership(user_id=dana.id, org_id=acme.id, role=OrgRole.member).save()
    await OrgMembership(user_id=dana.id, org_id=solo.id, role=OrgRole.owner).save()

    production = await Workspace(id=fixture_id("workspace:acme:production"), org_id=acme.id, name="Production", slug="production").save()
    staging = await Workspace(id=fixture_id("workspace:acme:staging"), org_id=acme.id, name="Staging", slug="staging").save()
    default = await Workspace(id=fixture_id("workspace:solo:default"), org_id=solo.id, name="Default", slug="default").save()

    await DataPlaneInstance(
        instance_id=fixture_id("data-plane:global"),
        version="fixture-global",
        address="https://global.fixture.invalid",
        first_seen=now - timedelta(days=30),
        last_seen=now - timedelta(seconds=30),
    ).save()
    await DataPlaneInstance(
        instance_id=fixture_id("data-plane:acme"),
        org_id=acme.id,
        version="fixture-dedicated",
        address="https://acme.fixture.invalid",
        first_seen=now - timedelta(days=14),
        last_seen=now - timedelta(hours=2),
    ).save()

    await WorkspaceMembership(user_id=michel.id, workspace_id=production.id, org_id=acme.id, role=WorkspaceRole.admin).save()
    await WorkspaceMembership(user_id=dana.id, workspace_id=production.id, org_id=acme.id, role=WorkspaceRole.member).save()
    await WorkspaceMembership(user_id=michel.id, workspace_id=staging.id, org_id=acme.id, role=WorkspaceRole.admin).save()
    await WorkspaceMembership(user_id=dana.id, workspace_id=default.id, org_id=solo.id, role=WorkspaceRole.admin).save()

    await OrgInvitation(
        id=fixture_id("org-invitation:acme:new-member"),
        org_id=acme.id,
        email="new.member@example.com",
        org_role=OrgRole.member,
        token_hash=token_hash(ACME_MEMBER_INVITE_TOKEN),
        created_by_user_id=michel.id,
        expires_at=now + timedelta(days=7),
    ).save()
    await OrgInvitation(
        id=fixture_id("org-invitation:acme:production-viewer"),
        org_id=acme.id,
        email="production.viewer@example.com",
        org_role=OrgRole.member,
        workspace_id=production.id,
        workspace_role=WorkspaceRole.viewer,
        token_hash=token_hash(ACME_PRODUCTION_INVITE_TOKEN),
        created_by_user_id=michel.id,
        expires_at=now + timedelta(days=7),
    ).save()
    await OrgInvitation(
        id=fixture_id("org-invitation:acme:expired"),
        org_id=acme.id,
        email="expired.invite@example.com",
        org_role=OrgRole.admin,
        workspace_id=staging.id,
        workspace_role=WorkspaceRole.admin,
        token_hash=token_hash(ACME_EXPIRED_INVITE_TOKEN),
        created_by_user_id=michel.id,
        expires_at=now - timedelta(days=1),
    ).save()

    checkout = await inference_key(ACME_PROD_TOKEN, production, michel, label="checkout-service").save()
    ci = await inference_key(ACME_STAGING_TOKEN, staging, michel, label="ci").save()
    solo_key = await inference_key(SOLO_TOKEN, default, dana, label="default").save()
    await inference_key(ACME_RETIRED_TOKEN, production, dana, label="batch-jobs", revoked=True).save()

    team_credentials = await workspace_rule(
        production,
        name="Streaming team credentials",
        match=RequestMatch(kind="request", stream=True),
        action=CredentialAccess(kind="credential_access", scopes=("workspace", "org")),
    )
    await workspace_policy(
        production,
        name="Streaming uses team credentials",
        priority=10,
        target=AllKeys(kind="all_keys"),
        rules=(team_credentials,),
    )
    approved_models = await workspace_rule(
        production,
        name="Approved production models",
        match=AllRequests(kind="all_requests"),
        action=AllowedModels(kind="models", names=(OPENAI_GPT_4O_MINI, OPENAI_GPT_4O)),
    )
    await workspace_policy(
        production,
        name="Approved production models",
        priority=20,
        target=AllKeys(kind="all_keys"),
        rules=(approved_models,),
    )
    fallback = await workspace_rule(
        production,
        name="GPT-4o fallback",
        match=RequestMatch(kind="request", models=(OPENAI_GPT_4O,)),
        action=Fallback(
            kind="fallback",
            models=(ANTHROPIC_CLAUDE_OPUS, OPENAI_GPT_4O_MINI),
            on=("rate_limited", "upstream_unavailable", "timeout"),
            max_attempts=3,
            timeout_ms=30000,
        ),
    )
    await workspace_policy(
        production,
        name="GPT-4o fallback",
        priority=30,
        target=AllKeys(kind="all_keys"),
        rules=(fallback,),
    )
    for priority, (name, action) in enumerate(
        (
            ("Honor every request parameter", StrictParameters(kind="strict_parameters")),
            (
                "Production model price ceiling",
                PriceLimit(kind="price_limit", max_input_price_per_mtok=Decimal(100), max_output_price_per_mtok=Decimal(100)),
            ),
            ("Output token ceiling", RequestLimits(kind="request_limits", max_output_tokens=16384)),
        ),
        start=31,
    ):
        configured_rule = await workspace_rule(
            production,
            name=name,
            match=AllRequests(kind="all_requests"),
            action=action,
        )
        await workspace_policy(
            production,
            name=name,
            priority=priority,
            target=AllKeys(kind="all_keys"),
            rules=(configured_rule,),
        )
    maintenance = await workspace_rule(
        production,
        name="Maintenance denial",
        match=AllRequests(kind="all_requests"),
        action=DenyRequest(kind="deny", message="Inference is temporarily unavailable"),
    )
    await workspace_policy(
        production,
        name="Maintenance window",
        priority=40,
        enabled=False,
        target=AllKeys(kind="all_keys"),
        rules=(maintenance, team_credentials),
    )
    ci_provider = await workspace_rule(
        staging,
        name="OpenAI provider only",
        match=AllRequests(kind="all_requests"),
        action=AllowedProviders(kind="providers", names=("openai",)),
    )
    await workspace_policy(
        staging,
        name="CI provider allowlist",
        priority=10,
        target=SelectedKeys(kind="selected_keys", key_ids=(str(ci.id),)),
        rules=(ci_provider,),
    )
    monthly_budget = await workspace_rule(
        default,
        name="Monthly shared budget",
        match=AllRequests(kind="all_requests"),
        action=Budget(kind="budget", period="month", amount_usd=Decimal(250), sharing="shared"),
    )
    await workspace_policy(
        default,
        name="Monthly shared budget",
        priority=10,
        target=AllKeys(kind="all_keys"),
        rules=(monthly_budget,),
    )

    await ManagementKey(
        id=fixture_id("management-key:acme"),
        org_id=acme.id,
        user_id=michel.id,
        token_hash=token_hash(ACME_ACCESS_TOKEN),
        prefix=key_prefix(ACME_ACCESS_TOKEN, MANAGEMENT_KEY_PREFIX),
        permissions=sorted(permissions_for_org_role(OrgRole.owner), key=str),
        label="fixture-cli",
    ).save()
    await ManagementKey(
        id=fixture_id("management-key:instance-owner"),
        user_id=michel.id,
        token_hash=token_hash(INSTANCE_ACCESS_TOKEN),
        prefix=key_prefix(INSTANCE_ACCESS_TOKEN, MANAGEMENT_KEY_PREFIX),
        permissions=sorted(ALL_PERMISSIONS, key=str),
        label="fixture-admin",
    ).save()

    openai, anthropic = catalog["openai"], catalog["anthropic"]
    keys = [
        await provider_credential(store, openai, acme, workspace=production, name="primary", priority=10, status="live"),
        await provider_credential(store, openai, acme, workspace=production, name="backup", priority=50, status="rate_limited"),
        await provider_credential(store, openai, acme, workspace=production, name="retired", priority=90, enabled=False),
        await provider_credential(store, anthropic, acme, workspace=production, status="invalid"),
        await provider_credential(store, openai, acme, name="org-wide", priority=100, status="live"),
        await provider_credential(store, openai, solo, workspace=default),
    ]

    await record_usage(production, checkout, 1200, now)
    await record_usage(staging, ci, 360, now)
    await record_usage(default, solo_key, 84, now)

    return Fixtures(
        password=FIXTURE_PASSWORD,
        admin_email=michel.email,
        emails=[michel.email, dana.email],
        inference_token=ACME_PROD_TOKEN,
        org_access_token=ACME_ACCESS_TOKEN,
        instance_access_token=INSTANCE_ACCESS_TOKEN,
        invitation_tokens=[
            ("new.member@example.com", ACME_MEMBER_INVITE_TOKEN),
            ("production.viewer@example.com", ACME_PRODUCTION_INVITE_TOKEN),
        ],
        unresolved_providers=sorted({key.provider_name for key in keys if not key.fingerprint}),
    )
