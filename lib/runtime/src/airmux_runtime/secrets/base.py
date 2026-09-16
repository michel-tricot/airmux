from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, Self

from pydantic import BaseModel, ConfigDict

from contract import SecretPurpose, SecretRef

if TYPE_CHECKING:
    from types import TracebackType

FINGERPRINT_LENGTH: Final = 4
REDACTED: Final = "Secret(***)"
PLATFORM_SEGMENT: Final = "platform"
ABSENT_SEGMENT: Final = "_"


class Secret:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    @property
    def fingerprint(self) -> str:
        return self._value[-FINGERPRINT_LENGTH:]

    def __repr__(self) -> str:
        return REDACTED

    def __str__(self) -> str:
        return REDACTED


def path_segments(ref: SecretRef) -> tuple[str, ...]:
    return (
        ref.purpose.value,
        str(ref.org_id) if ref.org_id else PLATFORM_SEGMENT,
        str(ref.workspace_id) if ref.workspace_id else ABSENT_SEGMENT,
        ref.service,
        str(ref.secret_id),
    )


class SecretNotFoundError(LookupError):
    def __init__(self, ref: SecretRef) -> None:
        super().__init__(f"no value for {ref.purpose.value} secret {ref.secret_id}")
        self.ref = ref


class SecretStoreUnavailableError(RuntimeError):
    def __init__(self, ref: SecretRef, cause: str) -> None:
        super().__init__(f"secret store unavailable for {ref.purpose.value} secret {ref.secret_id}: {cause}")
        self.ref = ref


class SecretRejectedError(RuntimeError):
    def __init__(self, kind: str, ref: SecretRef, detail: str = "") -> None:
        super().__init__(detail or f"the {kind} secret store will not hold {ref.purpose.value} secret {ref.secret_id}")
        self.kind = kind
        self.ref = ref


class SecretReader(Protocol):
    async def get(self, ref: SecretRef) -> Secret: ...


class SecretStore(SecretReader, Protocol):
    async def put(self, ref: SecretRef, secret: Secret) -> None: ...

    async def delete(self, ref: SecretRef) -> None: ...


class _SecretAdapter(ABC):
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
    async def get(self, ref: SecretRef) -> Secret: ...

    async def put(self, ref: SecretRef, secret: Secret) -> None:  # noqa: ARG002 a refusal never touches the value
        raise SecretRejectedError(self.kind, ref)

    async def delete(self, ref: SecretRef) -> None:
        raise SecretRejectedError(self.kind, ref)

    async def aclose(self) -> None:
        return


class SecretStoreConfig(BaseModel, ABC):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str

    @abstractmethod
    def build(self) -> _SecretAdapter: ...


__all__ = [
    "Secret",
    "SecretNotFoundError",
    "SecretPurpose",
    "SecretReader",
    "SecretRef",
    "SecretRejectedError",
    "SecretStore",
    "SecretStoreConfig",
    "SecretStoreUnavailableError",
    "path_segments",
]
