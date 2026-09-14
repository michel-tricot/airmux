from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, ClassVar, Literal

from contract.secrets.base import Secret, SecretNotFoundError, SecretPurpose, SecretRejectedError, SecretStore, SecretStoreConfig

if TYPE_CHECKING:
    from contract.secrets.base import SecretRef

_NOT_NAMEABLE = re.compile(r"[^A-Z0-9]+")
DEFAULT_PREFIX = "TOKKEEPER_SECRET"
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

    Storing is a declaration rather than a write. The value already exists, because the operator
    exported it, so put() records nothing and only checks that what it is asked to hold is what the
    environment already resolves. It refuses the two cases that would otherwise mislead: a variable
    that is not set, which would leave a credential resolving to nothing, and a different value,
    which would mean the key the operator thinks they stored is not the one their traffic spends.
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

    async def put(self, ref: SecretRef, secret: Secret) -> Secret:
        """Accept a value the environment already holds; refuse to pretend about one it does not.

        Returns what the environment holds rather than the argument, which is the same value by the
        time this returns and stays true if that ever stops being enforced here.
        """
        try:
            held = await self.get(ref)
        except SecretNotFoundError as e:
            names = " or ".join(self.variables_for(ref))
            msg = f"this instance reads provider keys from the environment; set {names} instead"
            raise SecretRejectedError(self.kind, ref, msg) from e
        if held.reveal() != secret.reveal():
            msg = f"the environment already holds a different key for {ref.service}; change it there instead"
            raise SecretRejectedError(self.kind, ref, msg)
        return held

    async def delete(self, ref: SecretRef) -> None:
        """A no-op: the store does not own the variable. Removing the row that named it is what
        stops it being spent, because nothing resolves a ref no credential carries."""
