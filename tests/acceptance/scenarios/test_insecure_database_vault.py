from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import Stack


def test_a_running_data_plane_resolves_an_insecure_database_secret(stack: Stack) -> None:
    stack.write_config(secrets_kind="insecure_database")
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    response = stack.request()

    assert response.status_code == 200, response.text
    assert response.json()["content"] == [{"type": "text", "text": "ok"}]
    assert stack.upstream_requests == 1
