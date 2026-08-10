from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, ClassVar, Literal

from contract.secrets.base import Secret, SecretNotFoundError, SecretPurpose, SecretStore, SecretStoreConfig

if TYPE_CHECKING:
    from contract.secrets.base import SecretRef

_NOT_NAMEABLE = re.compile(r"[^A-Z0-9]+")
DEFAULT_PREFIX = "AIRLLM_SECRET"
CONVENTIONAL_SUFFIX = "API_KEY"


def _variable(*parts: str) -> str:
    return _NOT_NAMEABLE.sub("_", "_".join(parts).upper())


class EnvStoreConfig(SecretStoreConfig):
    kind: Literal["env"] = "env"
    prefix: str = DEFAULT_PREFIX

    def build(self) -> EnvSecretStore:
        return EnvSecretStore(prefix=self.prefix)


class EnvSecretStore(SecretStore):
    """Secrets from the process environment, keyed by what they authenticate to.

    A provider secret resolves to {SERVICE}_API_KEY, the name every provider SDK documents.
    {prefix}_{PURPOSE}_{SERVICE} takes precedence, for an environment that already means
    something else by OPENAI_API_KEY and as the only name a non-provider purpose answers to.

    Scope and name are deliberately not part of the lookup. The environment holds one value per
    provider and cannot hold more, so every credential for a provider resolves to the same variable
    whatever its row says. The consequence is worth stating plainly: an instance on this store bills
    every workspace to one upstream account per provider, so it serves single-tenant deployments and
    development, and BYOK on it is nominal. Per-tenant keys need a store that can hold more than one
    value per provider.

    Read only, because a value written here would live for one process and vanish. The control plane
    checks `writable` before offering to store a key.
    """

    kind: ClassVar[str] = "env"

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def variables_for(self, ref: SecretRef) -> tuple[str, ...]:
        """The names tried in order, most specific first."""
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
