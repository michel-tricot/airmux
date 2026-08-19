from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from pydantic import SecretStr  # noqa: TC002 pydantic resolves the config field type at runtime

from contract.secrets.base import (
    Secret,
    SecretNotFoundError,
    SecretRef,
    SecretStore,
    SecretStoreConfig,
    SecretStoreUnavailableError,
    path_segments,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import asyncpg

SELECT_VALUE = "SELECT value FROM insecure_vault_secret WHERE address = $1"
UPSERT_VALUE = "INSERT INTO insecure_vault_secret (address, value) VALUES ($1, $2) ON CONFLICT (address) DO UPDATE SET value = EXCLUDED.value"
DELETE_VALUE = "DELETE FROM insecure_vault_secret WHERE address = $1"


class InsecureDatabaseStoreConfig(SecretStoreConfig):
    kind: Literal["insecure_database"] = "insecure_database"
    url: SecretStr

    def build(self) -> InsecureDatabaseSecretStore:
        return InsecureDatabaseSecretStore(url=self.url.get_secret_value())


class InsecureDatabaseSecretStore(SecretStore):
    """A PostgreSQL store that persists secret values as plaintext.

    This backend is intentionally named insecure because database readers, backups, replicas, and
    transaction logs can all expose its values. Use it only where that tradeoff is understood.
    """

    kind: ClassVar[str] = "insecure_database"

    def __init__(self, url: str) -> None:
        self._url = url.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def get(self, ref: SecretRef) -> Secret:
        async with self._connection(ref) as connection:
            value = cast("str | None", await connection.fetchval(SELECT_VALUE, self.address_of(ref)))
        if value is None:
            raise SecretNotFoundError(ref)
        return Secret(value)

    async def put(self, ref: SecretRef, secret: Secret) -> Secret:
        async with self._connection(ref) as connection:
            await connection.execute(UPSERT_VALUE, self.address_of(ref), secret.reveal())
        return secret

    async def delete(self, ref: SecretRef) -> None:
        async with self._connection(ref) as connection:
            await connection.execute(DELETE_VALUE, self.address_of(ref))

    @staticmethod
    def address_of(ref: SecretRef) -> str:
        material = b"\x00".join(segment.encode("utf-8") for segment in path_segments(ref))
        return hashlib.sha256(material).hexdigest()

    @asynccontextmanager
    async def _connection(self, ref: SecretRef) -> AsyncIterator[asyncpg.Connection]:
        import asyncpg  # noqa: PLC0415 driver loads only when this backend performs an operation

        connection: asyncpg.Connection | None = None
        try:
            connection = await asyncpg.connect(self._url)
            yield connection
        except (OSError, asyncpg.PostgresError) as error:
            raise SecretStoreUnavailableError(ref, "database operation failed") from error
        finally:
            if connection is not None:
                with suppress(OSError, asyncpg.PostgresError):
                    await connection.close()
