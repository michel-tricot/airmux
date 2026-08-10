from __future__ import annotations

from typing import ClassVar, Literal

from contract.secrets.base import Secret, SecretNotFoundError, SecretRef, SecretStore, SecretStoreConfig, path_segments


class MemoryStoreConfig(SecretStoreConfig):
    kind: Literal["memory"] = "memory"

    def build(self) -> MemorySecretStore:
        return MemorySecretStore()


class MemorySecretStore(SecretStore):
    """An in-process store for tests and single-process development.

    Both planes sharing one instance is what makes the whole write-then-read path testable without
    infrastructure. It is not a deployment option: nothing survives a restart or reaches a second
    process.
    """

    kind: ClassVar[str] = "memory"

    def __init__(self) -> None:
        self._values: dict[tuple[str, ...], str] = {}

    async def get(self, ref: SecretRef) -> Secret:
        value = self._values.get(path_segments(ref))
        if value is None:
            raise SecretNotFoundError(ref)
        return Secret(value)

    async def put(self, ref: SecretRef, secret: Secret) -> Secret:
        self._values[path_segments(ref)] = secret.reveal()
        return secret

    async def delete(self, ref: SecretRef) -> None:
        self._values.pop(path_segments(ref), None)
