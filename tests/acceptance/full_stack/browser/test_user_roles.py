from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
from browser_support import invite_member, running_console
from playwright.sync_api import expect
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from browser_support import Console
    from stack_harness import Stack

CSRF = {"X-Requested-With": "XMLHttpRequest"}


def verify_org_switch(console: Console) -> None:
    page = console.page
    page.goto(f"{console.url}/orgs")
    page.get_by_role("button", name=re.compile("Second organization")).click()
    console.select_workspace("Second workspace")
    page.get_by_role("button", name="Switch organization", exact=True).click()
    page.get_by_role("button", name=re.compile("org-acc")).click()
    console.select_workspace("acceptance")
    page.get_by_role("combobox", name="Workspace", exact=True).click()
    expect(page.get_by_role("option", name="Second workspace", exact=True)).to_have_count(0)


def test_user_roles_are_managed_together_and_auditors_cannot_change_them(stack: Stack) -> None:
    with (
        running_console(stack) as console,
        httpx.Client(base_url=stack.cp_url, headers=CSRF) as admin,
        httpx.Client(base_url=stack.cp_url, headers=CSRF) as member,
    ):
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        org_path = f"/api/v1/organizations/{stack.org_id}"
        workspace = admin.get(f"{org_path}/workspaces").json()["data"][0]
        user_id = invite_member(admin, member, org_path, workspace["id"])
        second_org = admin.post("/api/v1/organizations", json={"name": "Second organization"}).json()["data"]
        second_workspace = admin.post(f"/api/v1/organizations/{second_org['id']}/workspaces", json={"name": "Second workspace"}).json()["data"]

        console.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        page = console.page
        page.goto(f"{console.url}/instance/users/{user_id}")
        for label, role in (
            ("Instance role", "Auditor"),
            ("Organization role in org-acc", "Admin"),
            ("Workspace role in acceptance", "Viewer"),
        ):
            page.get_by_role("combobox", name=label, exact=True).click()
            page.get_by_role("option", name=role, exact=True).click()
            page.get_by_role("button", name="Confirm role change", exact=True).click()
            expect(page.get_by_role("dialog")).to_have_count(0)
            expect(page.get_by_role("combobox", name=label, exact=True)).to_contain_text(role)

        page.get_by_role("button", name="Add to Organization", exact=True).click()
        dialog = page.get_by_role("dialog", name="Add to Organization", exact=True)
        dialog.get_by_role("combobox", name="Organization", exact=True).click()
        page.get_by_role("option", name="Second organization", exact=True).click()
        dialog.get_by_role("button", name="Add", exact=True).click()
        expect(page.get_by_role("combobox", name="Organization role in Second organization", exact=True)).to_contain_text("Member")

        page.get_by_role("button", name="Add to Workspace", exact=True).click()
        dialog = page.get_by_role("dialog", name="Add to Workspace", exact=True)
        dialog.get_by_role("combobox", name="Organization", exact=True).click()
        page.get_by_role("option", name="Second organization", exact=True).click()
        dialog.get_by_role("combobox", name="Workspace", exact=True).click()
        page.get_by_role("option", name="Second workspace", exact=True).click()
        dialog.get_by_role("combobox", name="Role", exact=True).click()
        page.get_by_role("option", name="Viewer", exact=True).click()
        dialog.get_by_role("button", name="Add", exact=True).click()
        expect(page.get_by_role("combobox", name="Workspace role in Second workspace", exact=True)).to_contain_text("Viewer")
        page.screenshot(path=str(stack.tmp / "user-roles-owner.png"), full_page=True)

        memberships = admin.get(f"/api/v1/users/{user_id}/memberships").json()["data"]
        assert {membership["role"] for membership in memberships["org_memberships"]} == {"admin", "member"}
        assert {membership["workspace_id"] for membership in memberships["workspace_memberships"]} == {workspace["id"], second_workspace["id"]}
        assert {membership["role"] for membership in memberships["workspace_memberships"]} == {"viewer"}
        assert stack.request("roles remain usable").status_code == 200

        page.get_by_role("button", name="Sign out", exact=True).click()
        console.login("browser-member@acceptance.test", "browser-member-password")
        page.goto(f"{console.url}/instance/users/{user_id}")
        expect(page.get_by_role("heading", name="Browser Member", exact=True)).to_be_visible()
        expect(page.get_by_role("combobox", name="Instance role", exact=True)).to_have_count(0)
        expect(page.get_by_role("combobox", name="Organization role in org-acc", exact=True)).to_have_count(0)
        expect(page.get_by_role("combobox", name="Workspace role in acceptance", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Add to Organization", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Add to Workspace", exact=True)).to_have_count(0)
        page.screenshot(path=str(stack.tmp / "user-roles-auditor.png"), full_page=True)
        verify_org_switch(console)
        page.screenshot(path=str(stack.tmp / "user-roles-org-switch.png"), full_page=True)
