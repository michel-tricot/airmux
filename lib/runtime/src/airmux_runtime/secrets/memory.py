from __future__ import annotations

from typing import ClassVar, Literal

from airmux_runtime.secrets.base import Secret, SecretNotFoundError, SecretRef, SecretStoreConfig, _SecretAdapter, path_segments


class MemoryStoreConfig(SecretStoreConfig):
    kind: Literal["memory"] = "memory"

    def build(self) -> MemorySecretStore:
        return MemorySecretStore()


class MemorySecretStore(_SecretAdapter):
    kind: ClassVar[str] = "memory"

    def __init__(self) -> None:
        self._values: dict[tuple[str, ...], str] = {}

    async def get(self, ref: SecretRef) -> Secret:
        value = self._values.get(path_segments(ref))
        if value is None:
            raise SecretNotFoundError(ref)
        return Secret(value)

    async def put(self, ref: SecretRef, secret: Secret) -> None:
        self._values[path_segments(ref)] = secret.reveal()

    async def delete(self, ref: SecretRef) -> None:
        self._values.pop(path_segments(ref), None)
