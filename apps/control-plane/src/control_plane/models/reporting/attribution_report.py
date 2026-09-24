from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import select as sql_select
from sqlmodel import col

from contract import UsdAmount
from contract.money import ZERO_USD
from control_plane.db import current_session
from control_plane.models.reporting.names import names_for_dimension
from control_plane.models.reporting.query import AttributionQuery, FilterOptionsQuery, Grouping, ReportQuery, ReportWindow
from control_plane.models.usage_event import UsageEvent

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class AttributionItemOut(BaseModel):
    id: str
    name: str
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: UsdAmount
    previous_cost_usd: UsdAmount


class AttributionReportOut(BaseModel):
    items: list[AttributionItemOut]
    next_offset: int | None

    @classmethod
    async def for_scope(cls, org_id: UUID, query: AttributionQuery, now: datetime) -> AttributionReportOut:
        window = query.window(now)
        current = await _grouped(org_id, query, window, query.group_by)
        previous_window = ReportWindow(
            start_at=window.previous_start_at,
            end_at=window.previous_end_at,
            previous_start_at=window.previous_start_at,
            previous_end_at=window.previous_end_at,
            timezone=window.timezone,
        )
        previous = await _grouped(org_id, query, previous_window, query.group_by)
        names = await names_for_dimension(org_id, query.workspace_id, query.group_by, [*current, *previous])
        items = [
            AttributionItemOut(
                id=identifier,
                name=names.get(identifier, identifier or ("No credential" if query.group_by == "credential" else "No provider attempt")),
                requests=values[0],
                input_tokens=values[1],
                output_tokens=values[2],
                cost_usd=values[3],
                previous_cost_usd=previous.get(identifier, (0, 0, 0, ZERO_USD))[3],
            )
            for identifier in current.keys() | previous.keys()
            for values in [current.get(identifier, (0, 0, 0, ZERO_USD))]
        ]
        if query.search:
            search = query.search.casefold()
            items = [item for item in items if search in item.name.casefold() or search in item.id.casefold()]
        if query.sort_by == "change":
            items.sort(key=lambda item: (item.cost_usd - item.previous_cost_usd, item.id), reverse=True)
        elif query.sort_by == "requests":
            items.sort(key=lambda item: (item.requests, item.id), reverse=True)
        else:
            items.sort(key=lambda item: (item.cost_usd, item.id), reverse=True)
        page = items[query.offset : query.offset + query.limit]
        return cls(items=page, next_offset=query.offset + query.limit if len(items) > query.offset + query.limit else None)


class FilterOptionOut(BaseModel):
    id: str
    name: str


class FilterOptionsOut(BaseModel):
    items: list[FilterOptionOut]

    @classmethod
    async def for_scope(cls, org_id: UUID, query: FilterOptionsQuery, now: datetime) -> FilterOptionsOut:
        filter_field = {
            "owner": "owner_id",
            "key": "key_id",
            "model": "model_id",
            "provider": "provider_id",
            "credential": "credential_id",
        }.get(query.dimension)
        scope_query = query.model_copy(update={filter_field: None}) if filter_field is not None else query
        groups = await _grouped(org_id, scope_query, query.window(now), query.dimension)
        names = await names_for_dimension(org_id, query.workspace_id, query.dimension, list(groups))
        identifiers = [identifier for identifier in groups if identifier or query.dimension != "credential"]
        if query.search:
            search = query.search.casefold()
            identifiers = [
                identifier for identifier in identifiers if search in names.get(identifier, identifier).casefold() or search in identifier.casefold()
            ]
        return cls(
            items=[
                FilterOptionOut(id=identifier, name=names.get(identifier, identifier))
                for identifier in sorted(identifiers, key=lambda identifier: names.get(identifier, identifier).casefold())
            ]
        )


async def _grouped(
    org_id: UUID,
    query: ReportQuery,
    window: ReportWindow,
    group_by: Grouping,
) -> dict[str, tuple[int, int, int, UsdAmount]]:
    grouping = {
        "workspace": col(UsageEvent.workspace_id),
        "owner": col(UsageEvent.user_id),
        "key": col(UsageEvent.key_id),
        "model": col(UsageEvent.model_id),
        "provider": col(UsageEvent.provider_id),
        "credential": col(UsageEvent.credential_id),
    }[group_by]
    statement = (
        sql_select(
            grouping,
            func.count(func.distinct(col(UsageEvent.request_id))),
            func.coalesce(func.sum(col(UsageEvent.input_tokens)), 0),
            func.coalesce(func.sum(col(UsageEvent.output_tokens)), 0),
            func.coalesce(func.sum(col(UsageEvent.cost_usd)), ZERO_USD),
        )
        .where(*query.conditions(org_id, window))
        .group_by(grouping)
    )
    return {
        str(values[0]) if values[0] is not None else "": (values[1], values[2], values[3], values[4])
        for values in (await current_session().execute(statement)).all()
    }
