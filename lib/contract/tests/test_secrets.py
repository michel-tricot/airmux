from __future__ import annotations

import json
import logging
import stat
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from contract import (
    EnvSecretStore,
    EnvStoreConfig,
    FileSecretStore,
    FileStoreConfig,
    InsecureDatabaseSecretStore,
    InsecureDatabaseStoreConfig,
    MemorySecretStore,
    MemoryStoreConfig,
    Secret,
    SecretNotFoundError,
    SecretPurpose,
    SecretRef,
    SecretRejectedError,
    SecretsConfig,
    SecretStoreUnavailableError,
)

ORG = uuid4()
WORKSPACE = uuid4()


class Configured(BaseModel):
    """A stand-in for a plane's config, which is where the union is actually parsed."""

    secrets: SecretsConfig


def a_ref(service="openai", name="default", org_id=ORG, workspace_id=WORKSPACE, purpose=SecretPurpose.provider):
    return SecretRef(purpose=purpose, service=service, name=name, secret_id=uuid4(), org_id=org_id, workspace_id=workspace_id)


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path):
    """Every writable store, so the facade is proved once rather than per backend."""
    configs = {"memory": MemoryStoreConfig(), "file": FileStoreConfig(root=tmp_path / "secrets")}
    return configs[request.param].build()


async def test_a_written_secret_reads_back(store):
    ref = a_ref()
    await store.put(ref, Secret("sk-provider-value"))
    assert (await store.get(ref)).reveal() == "sk-provider-value"


async def test_a_rotation_replaces_the_value_under_the_same_ref(store):
    ref = a_ref()
    await store.put(ref, Secret("first"))
    await store.put(ref, Secret("second"))
    assert (await store.get(ref)).reveal() == "second"


async def test_a_file_rotation_atomically_replaces_the_file(tmp_path):
    root = tmp_path / "secrets"
    store = FileSecretStore(root=root)
    ref = a_ref()
    await store.put(ref, Secret("first"))
    path = next(path for path in root.rglob("*") if path.is_file())
    first_inode = path.stat().st_ino

    await store.put(ref, Secret("second"))

    assert path.stat().st_ino != first_inode
    assert [candidate for candidate in root.rglob("*") if candidate.is_file()] == [path]
    assert (await store.get(ref)).reveal() == "second"


async def test_a_file_store_rejects_a_service_that_escapes_its_root(tmp_path):
    root = tmp_path / "secrets"
    escaped = tmp_path / "escaped"
    store = FileSecretStore(root=root)

    with pytest.raises(SecretRejectedError):
        await store.put(a_ref(service=str(escaped)), Secret("outside"))

    assert not escaped.exists()


async def test_a_file_store_rejects_a_symlinked_parent_that_escapes_its_root(tmp_path):
    root = tmp_path / "secrets"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "provider").symlink_to(outside, target_is_directory=True)
    store = FileSecretStore(root=root)

    with pytest.raises(SecretRejectedError):
        await store.put(a_ref(), Secret("outside"))

    assert list(outside.iterdir()) == []


async def test_a_deleted_secret_is_gone(store):
    ref = a_ref()
    await store.put(ref, Secret("doomed"))
    await store.delete(ref)
    with pytest.raises(SecretNotFoundError):
        await store.get(ref)


async def test_deleting_an_absent_secret_is_quiet(store):
    """Delete runs against credentials whose value may already be gone; that is not an error."""
    await store.delete(a_ref())


async def test_reading_an_unwritten_secret_is_not_found(store):
    with pytest.raises(SecretNotFoundError):
        await store.get(a_ref())


async def test_two_secrets_for_one_service_coexist(store):
    """The whole point of BYOK: a workspace holds several keys against the same provider."""
    primary = a_ref(name="primary")
    backup = a_ref(name="backup")
    await store.put(primary, Secret("primary-value"))
    await store.put(backup, Secret("backup-value"))
    assert (await store.get(primary)).reveal() == "primary-value"
    assert (await store.get(backup)).reveal() == "backup-value"


async def test_secrets_do_not_collide_across_services(store):
    openai = a_ref(service="openai")
    anthropic = a_ref(service="anthropic")
    await store.put(openai, Secret("one"))
    await store.put(anthropic, Secret("two"))
    assert (await store.get(openai)).reveal() == "one"
    assert (await store.get(anthropic)).reveal() == "two"


async def test_scopes_do_not_read_as_one_another(store):
    """A workspace secret and the org secret it shares an id with are different secrets."""
    secret_id = uuid4()

    def scoped(org_id=None, workspace_id=None):
        return SecretRef(
            purpose=SecretPurpose.provider, service="openai", name="default", secret_id=secret_id, org_id=org_id, workspace_id=workspace_id
        )

    workspace_scoped = scoped(org_id=ORG, workspace_id=WORKSPACE)
    org_scoped = scoped(org_id=ORG)
    platform_scoped = scoped()
    await store.put(workspace_scoped, Secret("workspace-value"))
    await store.put(org_scoped, Secret("org-value"))
    await store.put(platform_scoped, Secret("platform-value"))
    assert (await store.get(workspace_scoped)).reveal() == "workspace-value"
    assert (await store.get(org_scoped)).reveal() == "org-value"
    assert (await store.get(platform_scoped)).reveal() == "platform-value"


def test_a_config_builds_its_own_store(tmp_path):
    assert isinstance(MemoryStoreConfig().build(), MemorySecretStore)
    assert isinstance(FileStoreConfig(root=tmp_path).build(), FileSecretStore)
    assert isinstance(EnvStoreConfig().build(), EnvSecretStore)
    assert isinstance(InsecureDatabaseStoreConfig(url="postgresql://vault:secret@db/vault").build(), InsecureDatabaseSecretStore)


async def test_a_store_owns_its_async_lifecycle():
    store = MemoryStoreConfig().build()

    async with store as opened:
        assert opened is store


def test_the_kind_selects_which_backend_parses_the_settings(tmp_path):
    configured = Configured.model_validate({"secrets": {"kind": "file", "root": str(tmp_path)}})
    assert configured.secrets == FileStoreConfig(root=tmp_path)
    assert Configured.model_validate({"secrets": {"kind": "env", "prefix": "ACME"}}).secrets == EnvStoreConfig(prefix="ACME")
    configured = Configured.model_validate({"secrets": {"kind": "insecure_database", "url": "postgresql://vault:secret@db/vault"}})
    assert isinstance(configured.secrets, InsecureDatabaseStoreConfig)


def test_the_insecure_database_url_is_redacted():
    url = "postgresql://vault:secret@db/vault"
    config = InsecureDatabaseStoreConfig(url=url)

    assert url not in repr(config)
    assert config.kind == "insecure_database"


def test_a_backend_does_not_accept_another_backend_settings():
    """The point of splitting config per backend: `root` is a file store's business and nobody
    else's, so a typo lands as a validation error rather than as a silently ignored key."""
    with pytest.raises(ValidationError):
        Configured.model_validate({"secrets": {"kind": "env", "root": "somewhere/secrets"}})


def test_an_unknown_backend_is_refused():
    with pytest.raises(ValidationError):
        Configured.model_validate({"secrets": {"kind": "s3"}})


def test_secret_repr_and_str_are_redacted():
    secret = Secret("sk-do-not-print-me")
    assert "do-not-print-me" not in repr(secret)
    assert "do-not-print-me" not in str(secret)
    assert "do-not-print-me" not in f"{secret}"


def test_secret_does_not_serialize():
    with pytest.raises(TypeError):
        json.dumps({"credential": Secret("sk-do-not-print-me")})


def test_secret_does_not_reach_the_log(caplog):
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("using %s", Secret("sk-do-not-print-me"))
    assert "do-not-print-me" not in caplog.text


def test_secret_fingerprint_is_the_tail():
    assert Secret("sk-proj-abcd1234").fingerprint == "1234"


def test_reveal_is_the_only_way_out():
    assert Secret("sk-value").reveal() == "sk-value"


async def test_a_file_store_keeps_secrets_owner_readable(tmp_path):
    store = FileSecretStore(root=tmp_path / "secrets")
    ref = a_ref()
    await store.put(ref, Secret("sk-value"))
    written = next(path for path in (tmp_path / "secrets").rglob("*") if path.is_file())
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    directories = [tmp_path / "secrets", *(path for path in (tmp_path / "secrets").rglob("*") if path.is_dir())]
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in directories)


async def test_a_file_store_reports_an_unusable_root_as_unavailable(tmp_path):
    """A root that cannot be written is infrastructure failing, not a credential that is absent."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    store = FileSecretStore(root=blocker)
    with pytest.raises(SecretStoreUnavailableError):
        await store.put(a_ref(), Secret("sk-value"))


def a_platform_ref(service="openai", name="default"):
    return SecretRef(purpose=SecretPurpose.provider, service=service, name=name, secret_id=uuid4())


async def test_an_env_store_resolves_a_provider_by_its_conventional_variable(monkeypatch):
    """OPENAI_API_KEY is the name every provider SDK documents and the one taxonomy.yml already
    used, so an operator running on the environment configures nothing new."""
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
    assert (await store.get(a_platform_ref())).reveal() == "sk-openai"
    assert (await store.get(a_platform_ref(service="anthropic"))).reveal() == "sk-anthropic"


async def test_every_credential_for_one_provider_resolves_to_the_same_variable(monkeypatch):
    """The environment holds one key per provider and cannot hold more, so scope and name do not
    enter the lookup. An instance on this store has one upstream account per provider, whatever its
    credential rows say."""
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-only-one")
    workspace_key = a_ref(name="primary")
    other_workspace_key = a_ref(name="backup", workspace_id=uuid4())
    platform_key = a_platform_ref()
    for ref in (workspace_key, other_workspace_key, platform_key):
        assert (await store.get(ref)).reveal() == "sk-the-only-one"


async def test_a_prefixed_variable_overrides_the_conventional_one(monkeypatch):
    """The escape hatch for an operator whose environment already means something else by
    OPENAI_API_KEY, and the only name a non-provider purpose would ever answer to."""
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    monkeypatch.setenv("TOKKEEPER_SECRET_PROVIDER_OPENAI", "sk-explicit")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-conventional")
    assert (await store.get(a_platform_ref())).reveal() == "sk-explicit"
    assert (await store.get(a_ref())).reveal() == "sk-explicit"


async def test_a_missing_env_secret_is_not_found(monkeypatch):
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    ref = a_platform_ref(service="nowhere")
    for variable in store.variables_for(ref):
        monkeypatch.delenv(variable, raising=False)
    with pytest.raises(SecretNotFoundError):
        await store.get(ref)


async def test_the_env_store_accepts_a_key_it_already_holds(monkeypatch):
    """In env mode a value is not written, it already exists: the operator exported it and the ref
    resolves to it. Storing one is therefore a declaration that it is in use, not a write, and
    refusing it would leave an instance that cannot record a key it can already read."""
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-operators-own")
    ref = a_platform_ref()

    await store.put(ref, Secret("sk-the-operators-own"))

    assert (await store.get(ref)).reveal() == "sk-the-operators-own"


async def test_the_env_store_says_which_variable_is_missing(monkeypatch):
    """The one case it cannot accept: nothing to declare. A row whose value resolves to nothing is
    one the data plane answers 502 for, so the refusal names the variable that would fix it."""
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TOKKEEPER_SECRET_PROVIDER_OPENAI", raising=False)

    with pytest.raises(SecretRejectedError, match="OPENAI_API_KEY"):
        await store.put(a_platform_ref(), Secret("sk-anything"))


async def test_the_env_store_refuses_to_diverge_from_the_environment(monkeypatch):
    """Accepting a different value silently would mean the credential the operator thinks they
    stored is not the one their traffic spends."""
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-operators-own")

    with pytest.raises(SecretRejectedError, match="environment"):
        await store.put(a_platform_ref(), Secret("sk-something-else"))


async def test_deleting_an_env_credential_leaves_the_variable(monkeypatch):
    """The store does not own the variable, so removing a credential removes the row that named it.
    Nothing resolves it afterwards because nothing names it."""
    store = EnvSecretStore(prefix="TOKKEEPER_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-operators-own")

    await store.delete(a_platform_ref())

    assert (await store.get(a_platform_ref())).reveal() == "sk-the-operators-own"


async def test_put_hands_back_what_the_store_now_holds(store):
    """So a caller describing the credential it just stored never has to read it back to do it."""
    ref = a_ref()

    held = await store.put(ref, Secret("sk-provider-value"))

    assert held.reveal() == (await store.get(ref)).reveal()
    assert held.fingerprint == "alue"
