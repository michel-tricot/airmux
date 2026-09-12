from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
from browser_support import invite_member, running_console
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD
from playwright.sync_api import expect

if TYPE_CHECKING:
    from conftest import Stack


def test_membership_removal_clears_open_tabs_history_and_playground(stack: Stack) -> None:
    with (
        running_console(stack) as console,
        httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "fetch"}) as admin,
        httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "fetch"}) as member,
    ):
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        org_path = f"/api/v1/orgs/{stack.org_id}"
        workspace = admin.get(f"{org_path}/workspaces").json()["data"][0]
        user_id = invite_member(admin, member, org_path, workspace["id"])
        alternate = admin.post("/api/v1/orgs", json={"name": "retained-org"}).json()["data"]
        alternate_path = f"/api/v1/orgs/{alternate['id']}"
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
        console.capture("membership-before-removal")
        admin.delete(f"{org_path}/users/{user_id}").raise_for_status()
        expect(page.get_by_text("private conversation marker", exact=True)).not_to_be_visible(timeout=15_000)
        for tab in (page, second):
            expect(tab.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("retained-workspace", timeout=15_000)
            assert tab.evaluate("localStorage.getItem('airllm_org_id')") == alternate["id"]
            tab.reload()
            expect(tab.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("retained-workspace")
            tab.go_back()
            expect(tab.get_by_text("private conversation marker", exact=True)).not_to_be_visible()
            expect(tab.get_by_role("combobox", name="Workspace", exact=True)).not_to_contain_text("acceptance")
            tab.get_by_role("combobox", name="Workspace", exact=True).click()
            tab.get_by_role("option", name="retained-workspace", exact=True).click()
            expect(tab.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("retained-workspace")
        console.capture("membership-after-removal")
