from __future__ import annotations

import time
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import pytest
import yaml
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, MODEL, _bin, _payload, _poll, metric
from tests.acceptance.process_harness import uvicorn_port

if TYPE_CHECKING:
    from stack_harness import Stack


def _start_two_deployments(stack: Stack) -> tuple[str, str]:
    stack.write_config(poll_interval_s=3600)
    stack.start_cp()
    stack.collect_credentials()
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        models = yaml.safe_load((stack.tmp / "taxonomy.yml").read_text())["models"]
        model = next(model for model in models if model["model_id"] == MODEL)
        _payload(admin.post("/api/v1/instance/taxonomy/models", json={**model, "input_price_per_mtok": "1", "output_price_per_mtok": "2"}))
    operational = {"authorization": f"Bearer {stack.env['AIRMUX_DATAPLANE_TOKEN']}"}

    def priced_bundle_ready():
        manifest = _payload(httpx.get(f"{stack.cp_url}/api/v1/bundles/manifest", headers=operational))
        entry = next((entry for entry in manifest["bundles"] if entry["org_id"] == stack.org_id), None)
        if entry is None:
            return False
        bundle = _payload(httpx.get(f"{stack.cp_url}/api/v1/bundles/{entry['bundle_id']}", headers=operational))
        return bool(bundle["keys"] and bundle["catalog"]["credentials"]) and any(
            model["model_id"] == MODEL and Decimal(model["input_price_per_mtok"]) == 1 for model in bundle["catalog"]["models"]
        )

    assert _poll(priced_bundle_ready, 30)
    stack.start_dp()
    stack.wait_dp_ready()
    second_config = yaml.safe_load(stack.config_path.read_text())
    second_cache = str(stack.tmp / "second-cache")
    second_config["data_plane"]["bundle"]["cache_dir"] = second_cache
    second_config["data_plane"]["events"]["cache_dir"] = second_cache
    second_path = stack.tmp / "second.yml"
    second_path.write_text(yaml.safe_dump(second_config))
    stack._spawn("dp-second", [_bin("airmux"), "gateway", "serve", "--host", "127.0.0.1", "--port", "0", "--config", str(second_path)])
    second_log = stack.tmp / "dp-second.log"
    assert _poll(lambda: uvicorn_port(second_log) is not None, 30)
    second_url = f"http://127.0.0.1:{uvicorn_port(second_log)}"
    assert _poll(lambda: httpx.get(f"{second_url}/readyz").status_code == 200, 30)
    return stack.dp_url, second_url


@pytest.mark.parametrize("stream", [False, True])
def test_two_deployments_enforce_historical_budgets_without_bundle_refresh(stack: Stack, stream: bool):
    urls = _start_two_deployments(stack)
    authentication = {"authorization": f"Bearer {stack.caller_api_key}"}
    body = {"model": MODEL, "messages": [{"role": "user", "content": "historical spending"}], "stream": stream}
    for url in urls:
        assert httpx.post(f"{url}/inf/v1/chat/completions", headers=authentication, json=body).status_code == 200
    assert _poll(lambda: len(stack.events()) == 2, 15)
    costs = [Decimal(event["cost_usd"]) for event in stack.events()]
    allowance = (sum(costs) * Decimal("0.75")).quantize(Decimal("0.000000000001"))
    assert max(costs) < allowance < sum(costs)
    assert {event["requested_model_id"] for event in stack.events()} == {MODEL}
    upstream_before = stack.upstream_requests
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        workspace = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/workspaces"))[0]
        path = f"/api/v1/organizations/{stack.org_id}/workspaces/{workspace['id']}/policies"
        definition = {
            "target": {"kind": "workspace"},
            "rules": [
                {"match": {"kind": "all_requests"}, "action": {"kind": "budget", "amount_usd": amount, "period": period, "scope": "shared"}}
                for amount, period in ((str(allowance), "month"), ("100", "day"))
            ],
        }
        for _ in range(2):
            policy = _payload(admin.post(path, json={"name": "Historical limits", "definition": definition}))
            committed = time.time()
            assert _poll(
                lambda committed=committed: all(
                    metric(f"{url}/metrics", "airmux_data_plane_budget_state_computed_timestamp_seconds") > committed for url in urls
                ),
                20,
            )
            for url in urls:
                response = httpx.post(f"{url}/inf/v1/chat/completions", headers=authentication, json=body)
                assert response.status_code == 429, response.text
                assert response.json()["error"]["code"] == "budget_exhausted"
                assert int(response.headers["retry-after"]) > 0
            assert stack.upstream_requests == upstream_before
            status = _payload(admin.get(f"{path}/{policy['id']}/status"))
            assert all(Decimal(budget["spent_usd"]) == sum(costs) for budget in status["budgets"])
            _payload(admin.delete(f"{path}/{policy['id']}"))
        _payload(admin.post(path, json={"name": "Outage limit", "definition": definition}))
        committed = time.time()
        assert _poll(
            lambda committed=committed: all(
                metric(f"{url}/metrics", "airmux_data_plane_budget_state_computed_timestamp_seconds") > committed for url in urls
            ),
            20,
        )
    stack.stop("cp")
    for url in urls:
        started = time.monotonic()
        response = httpx.post(f"{url}/inf/v1/chat/completions", headers=authentication, json=body, timeout=2)
        assert response.status_code == 429
        assert time.monotonic() - started < 1
