from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


def api_set(model: type, name: str) -> frozenset[str]:
    """Union the class's own api_* declaration with every mixin's, not first-wins like attribute lookup."""
    return frozenset().union(*(vars(base).get(name, ()) for base in model.__mro__))


def api_dispositions(model: type) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(hidden, readonly, immutable) composed across the MRO; hidden beats readonly beats immutable, so policy can tighten but never loosen."""
    hidden = api_set(model, "api_hidden")
    readonly = api_set(model, "api_readonly") - hidden
    immutable = api_set(model, "api_immutable") - hidden - readonly
    return hidden, readonly, immutable


class Envelope[T](BaseModel):
    """Every API response is {"data": <payload>}."""

    data: T


class DeletedOut[I](BaseModel):
    """Action result for every DELETE that removes a resource: its id and when it was deleted.

    Composite keys join their parts with / (the audit-log record_id convention). Revocations are
    not deletions; a revoked row survives and keeps its own action result.
    """

    id: I
    deleted_at: datetime


class ApiOut(BaseModel):
    """Resource representation, named <Table>Out; test_api_parity pairs it by name and holds it to the table minus api_hidden.

    Computed response fields that are not table columns go in api_extra. Action results (minted
    secrets, statuses) are plain BaseModel, not ApiOut.
    """

    model_config = ConfigDict(from_attributes=True)

    api_extra: ClassVar[frozenset[str]] = frozenset()


class ApiCreate(BaseModel):
    """Create body for a table resource, named <Table>Create; test_api_parity holds it to the writable columns."""


class ApiPatch(BaseModel):
    """Patch body for a table resource, named <Table>Patch; every field is `T | None = None` so exclude_unset gives partial updates."""
