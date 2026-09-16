from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field

from control_plane.models.common.base import Record


class Envelope[T](BaseModel):
    """Every API response is {"data": <payload>}."""

    data: T


class PageInfo(BaseModel):
    next_cursor: str | None


class PageEnvelope[T](Envelope[list[T]]):
    data: list[T] = Field(max_length=200)
    page: PageInfo

    @classmethod
    def from_slice[Source](cls, page: PageSlice[Source], output: type[T] | Callable[[Source], T] | None = None) -> Self:
        if output is None:
            items = list(page.items)
        elif isinstance(output, type) and issubclass(output, BaseModel):
            items = [output.model_validate(item) for item in page.items]
        else:
            items = [output(item) for item in page.items]
        return cls(data=items, page=PageInfo(next_cursor=page.next_cursor))


class DeletedOut[I](BaseModel):
    """Action result for every DELETE that removes a resource: its id and when it was deleted.

    Composite keys join their parts with / (the audit-log record_id convention). Revocations are
    not deletions; a revoked row survives and keeps its own action result.
    """

    id: I
    deleted_at: datetime

    @classmethod
    def of(cls, ident: I) -> Self:
        return cls(id=ident, deleted_at=datetime.now(tz=UTC))


class RecordOut[T: Record](BaseModel):
    """The wire representation of a table, declared as RecordOut[Table]; test_api_parity holds it to the table minus api_hidden.

    The type argument is the pairing: no name convention, the tests read it from the class.
    Computed response fields that are not table columns go in api_extra. Action results (minted
    secrets, statuses) are plain BaseModel, not RecordOut.
    """

    model_config = ConfigDict(from_attributes=True)

    api_extra: ClassVar[frozenset[str]] = frozenset()


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RecordCreate[T: Record](RequestModel):
    """Create body for a table resource, declared as RecordCreate[Table]; test_api_parity holds it to the writable columns."""


class RecordUpdate[T: Record](RequestModel):
    """Update body for a table resource, declared as RecordUpdate[Table]; every field is `T | None = None` so exclude_unset gives partial updates."""


if TYPE_CHECKING:
    from collections.abc import Callable

    from control_plane.models.common.pagination import PageSlice
