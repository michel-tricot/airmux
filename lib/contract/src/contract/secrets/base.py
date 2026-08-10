"""What a secret value is, which secret a caller means, and the one API for reaching it.

A store is named once in config and every access after that is the same three calls, so nothing
outside this package knows whether the value sits in a file, in an environment variable, or in a
vault. Callers name a secret with a SecretRef and never with a path: where a store keeps a value is
its own business, so there is no location string for anyone to author, forge, or leak.

Provider credentials are the first thing kept here and the reason the package exists, but nothing
in it is provider-shaped: a SecretRef says what a secret is for, so a signing key, an outbound
integration credential, or anything else the platform holds on someone's behalf lands here without
a second mechanism.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from uuid import UUID

FINGERPRINT_LENGTH: Final = 4
REDACTED: Final = "Secret(***)"
PLATFORM_SEGMENT: Final = "platform"
ABSENT_SEGMENT: Final = "_"


class Secret:
    """A secret value held in memory, wrapped so it cannot leak by accident.

    repr and str are redacted and the object has no serialization of its own, so json.dumps and a
    pydantic dump both raise rather than quietly emitting the value. reveal() is the only way out,
    which makes every call site that uses it a place worth reading twice.

    The value is a Python str, so it cannot be zeroed: the interpreter may keep copies alive until
    garbage collection and beyond. This wrapper narrows accidental disclosure, not memory forensics.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    @property
    def fingerprint(self) -> str:
        """The last few characters, the one derivative safe to persist and show in a listing."""
        return self._value[-FINGERPRINT_LENGTH:]

    def __repr__(self) -> str:
        return REDACTED

    def __str__(self) -> str:
        return REDACTED


class SecretPurpose(StrEnum):
    """What family a secret belongs to. Both planes must agree, which is why it lives here.

    A new purpose is one member, and every store keeps it apart from the others without changing.
    """

    provider = "provider"


@dataclass(frozen=True)
class SecretRef:
    """Which secret, said in terms of the domain rather than of any store's layout.

    purpose is the family, service is what inside that family the secret authenticates to (a
    provider name today), and name is the caller-facing handle that lets one service hold several.
    secret_id is what actually makes a ref unique; the rest is carried so a store with somewhere
    legible to put it can.

    org_id and workspace_id are absent for a platform secret and org_id alone is present for an org
    one, so the same two fields express all three scopes.
    """

    purpose: SecretPurpose
    service: str
    name: str
    secret_id: UUID
    org_id: UUID | None = None
    workspace_id: UUID | None = None

    @property
    def is_platform(self) -> bool:
        return self.org_id is None


def path_segments(ref: SecretRef) -> tuple[str, ...]:
    """A hierarchical address for stores that have a hierarchy.

    Fixed depth, so an org secret and a workspace secret can never resolve to the same place, and
    the secret id is the leaf, so two secrets for one service coexist. Purpose leads, so a store
    that wants to keep families apart (its own mount, its own policy) can split on one segment.
    """
    return (
        ref.purpose.value,
        str(ref.org_id) if ref.org_id else PLATFORM_SEGMENT,
        str(ref.workspace_id) if ref.workspace_id else ABSENT_SEGMENT,
        ref.service,
        str(ref.secret_id),
    )


class SecretNotFoundError(LookupError):
    """No value for this secret. A fact about the secret, so the request path may cache it."""

    def __init__(self, ref: SecretRef) -> None:
        super().__init__(f"no value for {ref.purpose.value} secret {ref.secret_id}")
        self.ref = ref


class SecretStoreUnavailableError(RuntimeError):
    """The store could not answer. A fact about infrastructure, so the request path may not cache it,
    and must never read it as permission to fall back to a broader scope."""

    def __init__(self, ref: SecretRef, cause: str) -> None:
        super().__init__(f"secret store unavailable for {ref.purpose.value} secret {ref.secret_id}: {cause}")
        self.ref = ref


class SecretStoreReadOnlyError(RuntimeError):
    """A write against a store that only reads. The control plane checks `writable` at startup so
    this surfaces as a misconfiguration rather than as a failed credential creation."""

    def __init__(self, kind: str, ref: SecretRef) -> None:
        super().__init__(f"the {kind} secret store is read only, refusing {ref.purpose.value} secret {ref.secret_id}")
        self.kind = kind
        self.ref = ref


class SecretStore(ABC):
    """The only way either plane touches a secret value.

    Read-only stores implement get() and inherit the refusals, so a backend declares what it can do
    by what it overrides.
    """

    kind: ClassVar[str]
    writable: ClassVar[bool] = False

    @abstractmethod
    async def get(self, ref: SecretRef) -> Secret:
        """The value, or SecretNotFoundError if there is none, or SecretStoreUnavailableError if the
        store could not say."""

    async def put(self, ref: SecretRef, secret: Secret) -> None:  # noqa: ARG002 refusing a write never touches the value
        """Write the value, replacing any previous one. A rotation is a put against the same ref."""
        raise SecretStoreReadOnlyError(self.kind, ref)

    async def delete(self, ref: SecretRef) -> None:
        """Remove the value for good, history included. Deleting what is not there is not an error,
        because delete is called on records whose value may already be gone."""
        raise SecretStoreReadOnlyError(self.kind, ref)


class SecretStoreConfig(BaseModel, ABC):
    """What one store needs, declared beside that store and nowhere else.

    A backend brings its own settings and builds its own instance, so adding one is a single new
    module plus a member in the SecretsConfig union. There is no shared config object collecting
    every backend's fields and no factory with a branch per kind.

    Extra keys are refused: a setting meant for another backend, or a misspelled one, means the
    store is not configured the way whoever wrote it believes, and a store quietly running on
    defaults is how secrets end up somewhere nobody intended.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str

    @abstractmethod
    def build(self) -> SecretStore:
        """The store this config describes."""
