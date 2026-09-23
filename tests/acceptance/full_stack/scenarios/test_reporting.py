from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO
from typing import TYPE_CHECKING

import httpx
from stack_harness import _payload, _poll

if TYPE_CHECKING:
    from stack_harness import Stack


def test_delivered_gateway_events_reconcile_across_reports(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    successful = stack.request()
    limited = stack.request("rate-limited")
    assert successful.status_code == 200, successful.text
    assert limited.status_code == 429, limited.text
    request_ids = {successful.headers["x-request-id"], limited.headers["x-request-id"]}
    assert _poll(lambda: request_ids <= {event["request_id"] for event in stack.events()}, 15)
    events = {event["request_id"]: event for event in stack.events() if event["request_id"] in request_ids}
    assert len(events) == 2
    assert {event["status"] for event in events.values()} == {"ok", "rate_limited"}
    assert events[successful.headers["x-request-id"]]["cache_read_tokens"] == 4

    report_path = f"/api/v1/organizations/{stack.org_id}/reports"
    authorization = {"authorization": f"Bearer {stack.env['AIRMUX_MANAGEMENT_KEY']}"}
    with httpx.Client(base_url=stack.cp_url, headers=authorization, timeout=10) as client:
        usage = _payload(client.get(f"{report_path}/usage"))
        totals = usage["totals"]
        assert totals["requests"] == 2
        for field in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
            assert totals[field] == sum(event[field] for event in events.values())
        expected_cost = sum((Decimal(event["cost_usd"]) for event in events.values()), Decimal(0))
        assert Decimal(totals["cost_usd"]) == expected_cost
        assert sum(day["requests"] for day in usage["daily"]) == 2

        workspace_id = next(iter(events.values()))["workspace_id"]
        scoped = _payload(client.get(f"{report_path}/usage", params={"workspace_id": workspace_id}))
        assert scoped["totals"] == totals

        requests = _payload(client.get(f"{report_path}/requests"))["requests"]
        assert {request["request_id"] for request in requests} == request_ids
        for request in requests:
            event = events[request["request_id"]]
            assert request["status"] == event["status"]
            assert request["attempt_count"] == 1
            assert Decimal(request["cost_usd"]) == Decimal(event["cost_usd"])
            detail = _payload(client.get(f"{report_path}/requests/{request['request_id']}"))
            assert [attempt["event_id"] for attempt in detail["attempts"]] == [event["event_id"]]
            assert detail["cache_read_tokens"] == event["cache_read_tokens"]

        attribution = _payload(client.get(f"{report_path}/attribution", params={"group_by": "provider"}))["items"]
        assert sum(item["requests"] for item in attribution) == 2
        assert sum((Decimal(item["cost_usd"]) for item in attribution), Decimal(0)) == expected_cost

        export = _payload(client.get(f"{report_path}/requests/export"))["csv"]
        rows = list(csv.DictReader(StringIO(export)))
        assert {request["request_id"] for request in rows} == request_ids
        assert sum((Decimal(request["cost_usd"]) for request in rows), Decimal(0)) == expected_cost
