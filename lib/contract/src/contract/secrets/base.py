"""What a secret value is, which secret a caller means, and the one API for reaching it.

A store is named once in config and every access after that is the same three calls, so nothing
outside this package knows whether the value sits in a file, in an environment variable, or in a
vault. Callers name a secret with a SecretRef and never with a path: where a store keeps a value is
its own business, so there is no location string for anyone to author, forge, or leak.

Provider credentials are the first thing kept here and the reason the package exists, but nothing
in it is provider-shaped: a SecretRef says what a secret is for, so an outbound integration
credential or anything else the platform holds on someone's behalf lands here without
a second mechanism.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final, Self
from uuid import UUID  # noqa: TC003 SecretRef crosses the wire inside the bundle, so pydantic resolves this at runtime

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from types import TracebackType

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
    """The kind of credential addressed by a secret reference."""

    provider = "provider"


@dataclass(frozen=True)
class SecretRef:
    """A stable reference to a secret value and the scope that owns it."""

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


class SecretRejectedError(RuntimeError):
    """The store will not hold this value."""

    def __init__(self, kind: str, ref: SecretRef, detail: str = "") -> None:
        super().__init__(detail or f"the {kind} secret store will not hold {ref.purpose.value} secret {ref.secret_id}")
        self.kind = kind
        self.ref = ref


class SecretStore(ABC):
    """The only way either plane touches a secret value.

    A store that only reads implements get() and inherits the refusals, so a backend declares what
    it can do by what it overrides rather than by advertising a capability nobody can act on until
    the value arrives.
    """

    kind: ClassVar[str]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    @abstractmethod
    async def get(self, ref: SecretRef) -> Secret:
        """The value, or SecretNotFoundError if there is none, or SecretStoreUnavailableError if the
        store could not say."""

    async def put(self, ref: SecretRef, secret: Secret) -> Secret:  # noqa: ARG002 a refusal never touches the value
        """Store the value, replacing any previous one, and return what the store now holds.

        A rotation is a put against the same ref.
        """
        raise SecretRejectedError(self.kind, ref)

    async def delete(self, ref: SecretRef) -> None:
        """Remove the value for good, history included. Deleting what is not there is not an error,
        because delete is called on records whose value may already be gone."""
        raise SecretRejectedError(self.kind, ref)

    async def aclose(self) -> None:
        """Release resources held by this store."""
        return


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
