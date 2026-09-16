from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from browser_support import invite_member, running_console
from playwright.sync_api import expect
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from stack_harness import Stack

CSRF = {"X-Requested-With": "XMLHttpRequest"}


def test_membership_removal_blocks_requests_and_reload_clears_private_state(stack: Stack) -> None:
    with (
        running_console(stack) as console,
        httpx.Client(base_url=stack.cp_url, headers=CSRF) as admin,
        httpx.Client(base_url=stack.cp_url, headers=CSRF) as member,
    ):
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        org_path = f"/api/v1/organizations/{stack.org_id}"
        workspace = admin.get(f"{org_path}/workspaces").json()["data"][0]
        user_id = invite_member(admin, member, org_path, workspace["id"])
        console.login("browser-member@acceptance.test", "browser-member-password")
        page = console.page
        page.get_by_role("link", name="Playground", exact=True).click()
        page.get_by_placeholder("Send a message... (Shift+Enter for newline)").fill("private conversation marker")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.get_by_text("tick0", exact=False)).to_be_visible()
        admin.delete(f"{org_path}/users/{user_id}").raise_for_status()
        assert member.get(f"{org_path}/workspaces").status_code == 403
        page.reload()
        expect(page.get_by_role("heading", name="Select Organization", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text("private conversation marker", exact=True)).not_to_be_visible()
        assert page.evaluate("localStorage.getItem('airmux_org_id')") is None
