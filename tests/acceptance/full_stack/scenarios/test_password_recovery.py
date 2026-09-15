from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import yaml
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from stack_harness import Stack


def test_password_change_rotates_the_current_browser_and_ends_other_sessions(stack: Stack) -> None:
    stack.write_config()
    configuration = yaml.safe_load(stack.config_path.read_text())
    configuration["control_plane"]["throttling"] = {
        "authentication": {"burst": 10, "per_second": 2},
        "account": {"burst": 10, "per_second": 2},
    }
    stack.config_path.write_text(yaml.safe_dump(configuration))
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    csrf = {"X-Requested-With": "XMLHttpRequest"}
    with (
        httpx.Client(base_url=stack.cp_url, headers=csrf, timeout=10.0) as current,
        httpx.Client(base_url=stack.cp_url, headers=csrf, timeout=10.0) as other,
    ):
        for browser in (current, other):
            browser.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        original_cookie = current.cookies["tokkeeper_session"]
        changed = current.post("/api/v1/auth/password", json={"current_password": ADMIN_PASSWORD, "new_password": "new-acceptance-password"})
        changed.raise_for_status()
        assert current.cookies["tokkeeper_session"] != original_cookie
        assert current.get("/api/v1/auth/me").status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401
        assert stack.request().status_code == 200
        assert other.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).status_code == 401
        other.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": "new-acceptance-password"}).raise_for_status()
