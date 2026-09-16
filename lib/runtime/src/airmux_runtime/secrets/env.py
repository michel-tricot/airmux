from __future__ import annotations

import os
import re
from typing import ClassVar, Literal

from airmux_runtime.secrets.base import Secret, SecretNotFoundError, SecretRejectedError, SecretStoreConfig, _SecretAdapter
from contract import SecretPurpose, SecretRef

_NOT_NAMEABLE = re.compile(r"[^A-Z0-9]+")
DEFAULT_PREFIX = "AIRMUX_SECRET"
CONVENTIONAL_SUFFIX = "API_KEY"


def _variable(*parts: str) -> str:
    return _NOT_NAMEABLE.sub("_", "_".join(parts).upper())


class EnvStoreConfig(SecretStoreConfig):
    kind: Literal["env"] = "env"
    prefix: str = DEFAULT_PREFIX

    def build(self) -> EnvSecretStore:
        return EnvSecretStore(prefix=self.prefix)


class EnvSecretStore(_SecretAdapter):
    kind: ClassVar[str] = "env"

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def variables_for(self, ref: SecretRef) -> tuple[str, ...]:
        prefixed = _variable(self.prefix, ref.purpose.value, ref.service)
        if ref.purpose is SecretPurpose.provider:
            return (prefixed, _variable(ref.service, CONVENTIONAL_SUFFIX))
        return (prefixed,)

    async def get(self, ref: SecretRef) -> Secret:
        for variable in self.variables_for(ref):
            value = os.environ.get(variable)
            if value is not None:
                return Secret(value)
        raise SecretNotFoundError(ref)

    async def put(self, ref: SecretRef, secret: Secret) -> None:
        try:
            held = await self.get(ref)
        except SecretNotFoundError as error:
            names = " or ".join(self.variables_for(ref))
            message = f"this instance reads provider keys from the environment; set {names} instead"
            raise SecretRejectedError(self.kind, ref, message) from error
        if held.reveal() != secret.reveal():
            message = f"the environment already holds a different key for {ref.service}; change it there instead"
            raise SecretRejectedError(self.kind, ref, message)

    async def delete(self, ref: SecretRef) -> None:
        del ref
