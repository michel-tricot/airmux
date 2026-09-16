from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, STUB_API_KEY, _payload, _poll

if TYPE_CHECKING:
    from stack_harness import Stack


def test_provider_rejects_missing_and_incorrect_credentials(stack: Stack) -> None:
    with httpx.Client(base_url=f"http://127.0.0.1:{stack.stub_port}") as provider:
        body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}
        assert provider.post("/chat/completions", json=body).status_code == 401
        assert provider.post("/chat/completions", headers={"Authorization": "Bearer incorrect"}, json=body).status_code == 401
        assert provider.post("/chat/completions", headers={"Authorization": f"Bearer {STUB_API_KEY}"}, json=body).status_code == 200


@pytest.mark.parametrize(("credential_value", "status", "event_status"), [(STUB_API_KEY, 200, "ok"), ("incorrect", 401, "credential_rejected")])
def test_a_running_data_plane_resolves_an_insecure_database_secret(stack: Stack, credential_value: str, status: int, event_status: str) -> None:
    stack.write_config(secrets_kind="insecure_database")
    stack.start_cp()
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}) as admin:
        _payload(admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}))
        credentials = _payload(admin.get(f"/api/v1/organizations/{stack.org_id}/provider-credentials"))
        credential = next(credential for credential in credentials if credential["provider_name"] == "stub")
        _payload(admin.put(f"/api/v1/organizations/{stack.org_id}/provider-credentials/{credential['id']}/value", json={"value": credential_value}))
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    response = stack.request()
    assert response.status_code == status, response.text
    assert stack.upstream_requests == 1
    assert _poll(lambda: len(stack.events()) == 1, 10)
    (event,) = stack.events()
    assert event["status"] == event_status
    assert event["credential_id"] == credential["id"]
    assert event["credential_scope"] == "org"
