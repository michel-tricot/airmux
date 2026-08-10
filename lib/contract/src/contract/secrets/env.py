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
    """Secrets from the process environment, read only.

    This is the store an operator points at for a single-tenant deployment whose provider keys
    already arrive as environment variables, and the one `airllm quickstart` uses so a first run
    needs no infrastructure. It cannot be written, so an instance configured this way serves
    platform secrets and refuses workspace BYOK as a startup-time misconfiguration rather than a
    runtime surprise.
    """

    kind: ClassVar[str] = "env"

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def variables_for(self, ref: SecretRef) -> tuple[str, ...]:
        """The names tried in order, most specific first.

        The derived name is {prefix}_{PURPOSE}_{SERVICE}_{NAME}, with the secret id appended for
        anything scoped, because service and name alone are only unique inside one workspace and the
        environment is flat.

        A platform provider credential also answers to {SERVICE}_API_KEY, the name every provider
        SDK already documents and the one taxonomy.yml has always used. That fallback is what lets
        an existing deployment keep its OPENAI_API_KEY and lets quickstart ask for nothing new.
        """
        derived = _variable(self.prefix, ref.purpose.value, ref.service, ref.name)
        if not ref.is_platform:
            return (_variable(derived, ref.secret_id.hex),)
        if ref.purpose is SecretPurpose.provider:
            return (derived, _variable(ref.service, CONVENTIONAL_SUFFIX))
        return (derived,)

    async def get(self, ref: SecretRef) -> Secret:
        for variable in self.variables_for(ref):
            value = os.environ.get(variable)
            if value is not None:
                return Secret(value)
        raise SecretNotFoundError(ref)
