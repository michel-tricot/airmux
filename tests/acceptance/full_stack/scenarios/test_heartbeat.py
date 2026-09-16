from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD, _poll

if TYPE_CHECKING:
    from stack_harness import Stack


def test_remote_bundle_admission_reports_a_heartbeat(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as admin:
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()

        def data_plane_online() -> bool:
            response = admin.get("/api/v1/instance/data-planes")
            response.raise_for_status()
            return len(response.json()["data"]) == 1

        assert _poll(data_plane_online, 10), "no heartbeat reached the instance roster"
