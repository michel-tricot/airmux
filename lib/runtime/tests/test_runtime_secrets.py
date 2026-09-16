from __future__ import annotations

import json
import stat
import subprocess
import sys
from typing import cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from airmux_runtime.secrets import (
    EnvSecretStore,
    FileStoreConfig,
    InsecureDatabaseStoreConfig,
    MemorySecretStore,
    Secret,
    SecretNotFoundError,
    SecretReader,
    SecretRejectedError,
    SecretsConfig,
    SecretStore,
)
from contract import SecretPurpose, SecretRef


class Configured(BaseModel):
    secrets: SecretsConfig


def ref() -> SecretRef:
    return SecretRef(purpose=SecretPurpose.provider, service="openai", name="default", secret_id=uuid4())


async def read(reader: SecretReader) -> Secret:
    return await reader.get(ref())


async def write(store: SecretStore) -> None:
    await store.put(ref(), Secret("value"))


@pytest.fixture(params=["memory", "file"])
def writable_store(request, tmp_path):
    if request.param == "memory":
        return MemorySecretStore()
    return FileStoreConfig(path=tmp_path / "secrets").build()


async def test_writable_stores_round_trip_rotate_and_delete(writable_store):
    secret_ref = ref()
    await writable_store.put(secret_ref, Secret("first"))
    assert (await writable_store.get(secret_ref)).reveal() == "first"

    await writable_store.put(secret_ref, Secret("second"))
    assert (await writable_store.get(secret_ref)).reveal() == "second"

    await writable_store.delete(secret_ref)
    with pytest.raises(SecretNotFoundError):
        await writable_store.get(secret_ref)


async def test_file_store_rejects_paths_and_symlinks_that_escape_its_root(tmp_path):
    root = tmp_path / "secrets"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "provider").symlink_to(outside, target_is_directory=True)
    store = FileStoreConfig(path=root).build()

    with pytest.raises(SecretRejectedError):
        await store.put(ref(), Secret("outside"))

    assert list(outside.iterdir()) == []


async def test_file_store_keeps_values_owner_readable(tmp_path):
    root = tmp_path / "secrets"
    store = FileStoreConfig(path=root).build()
    await store.put(ref(), Secret("private"))
    written = next(path for path in root.rglob("*") if path.is_file())

    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in (root, *(path for path in root.rglob("*") if path.is_dir())))


def test_secret_values_are_redacted_and_not_serializable():
    secret = Secret("private-value")

    assert "private-value" not in repr(secret)
    assert "private-value" not in str(secret)
    assert secret.fingerprint == "alue"
    with pytest.raises(TypeError):
        json.dumps({"secret": secret})


async def test_environment_store_uses_conventional_provider_variables(monkeypatch):
    secret_ref = ref()
    store = EnvSecretStore(prefix="AIRMUX_SECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-value")

    assert (await store.get(secret_ref)).reveal() == "provider-value"
    with pytest.raises(SecretRejectedError):
        await store.put(secret_ref, Secret("different"))


def test_memory_store_is_testable_but_not_deployable():
    store = MemorySecretStore()
    cast("SecretReader", store)
    cast("SecretStore", store)

    with pytest.raises(ValidationError):
        Configured.model_validate({"secrets": {"kind": "memory"}})


def test_file_store_is_deployable(tmp_path):
    configured = Configured.model_validate({"secrets": {"kind": "file", "path": str(tmp_path)}})

    assert configured.secrets == FileStoreConfig(path=tmp_path)


def test_database_adapter_names_the_missing_extra_without_disclosing_its_url(monkeypatch):
    url = "postgresql://user:private-password@database/airmux"
    monkeypatch.setitem(sys.modules, "asyncpg", None)

    with pytest.raises(RuntimeError, match=r"airmux-runtime\[insecure-database\]") as error:
        InsecureDatabaseStoreConfig(url=url).build()

    assert url not in str(error.value)


@pytest.mark.parametrize(
    "module",
    ["airmux_runtime.config", "airmux_runtime.secrets.base", "airmux_runtime.secrets.file"],
)
def test_base_runtime_imports_do_not_load_the_database_driver(module):
    result = subprocess.run(  # noqa: S603 the interpreter and parameterized module names are test-owned
        [sys.executable, "-c", f"import {module}, sys; assert 'asyncpg' not in sys.modules"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
