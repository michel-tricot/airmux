from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
from browser_support import invite_member, running_console
from playwright.sync_api import expect
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from stack_harness import Stack

CSRF = {"X-Requested-With": "XMLHttpRequest"}


def test_membership_removal_clears_open_tabs_and_playground_history(stack: Stack) -> None:
    with (
        running_console(stack) as console,
        httpx.Client(base_url=stack.cp_url, headers=CSRF) as admin,
        httpx.Client(base_url=stack.cp_url, headers=CSRF) as member,
    ):
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        org_path = f"/api/v1/organizations/{stack.org_id}"
        workspace = admin.get(f"{org_path}/workspaces").json()["data"][0]
        user_id = invite_member(admin, member, org_path, workspace["id"])
        alternate = admin.post("/api/v1/organizations", json={"name": "retained-org"})
        alternate.raise_for_status()
        alternate_org = alternate.json()["data"]
        alternate_path = f"/api/v1/organizations/{alternate_org['id']}"
        admin.put(f"{alternate_path}/users/{user_id}", json={"role": "admin"}).raise_for_status()
        admin.post(f"{alternate_path}/workspaces", json={"name": "retained-workspace"}).raise_for_status()
        console.login("browser-member@acceptance.test", "browser-member-password")
        page = console.page
        page.get_by_role("button", name=re.compile("org-acc")).click()
        page.get_by_role("link", name="Playground", exact=True).click()
        page.get_by_placeholder("Send a message... (Shift+Enter for newline)").fill("private conversation marker")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.get_by_text("tick0", exact=False)).to_be_visible()
        second = console.context.new_page()
        second.goto(page.url)
        expect(second.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("acceptance")
        admin.delete(f"{org_path}/users/{user_id}").raise_for_status()
        for tab in (page, second):
            expect(tab.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("retained-workspace", timeout=15_000)
            assert tab.evaluate("localStorage.getItem('airmux_org_id')") == alternate_org["id"]
            expect(tab.get_by_text("private conversation marker", exact=True)).not_to_be_visible()
            tab.reload()
            expect(tab.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("retained-workspace")
            expect(tab.get_by_text("private conversation marker", exact=True)).not_to_be_visible()
