from __future__ import annotations

import re
from typing import TYPE_CHECKING

import httpx
import pytest
from browser_support import invite_member, running_console
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD
from playwright.sync_api import expect

if TYPE_CHECKING:
    from conftest import Stack


def test_instance_owner_login_errors_navigation_dialogs_and_logout(stack: Stack) -> None:
    with running_console(stack) as console:
        page = console.page
        page.goto(console.url)
        page.get_by_label("Email", exact=True).fill(ADMIN_EMAIL)
        page.get_by_label("Password", exact=True).fill("incorrect-password")
        page.get_by_role("button", name="Sign in", exact=True).click()
        expect(page.get_by_text("Incorrect email or password", exact=True)).to_be_visible()
        console.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        page.goto(f"{console.url}/instance")
        expect(page.get_by_role("navigation", name="Instance navigation", exact=True)).to_be_visible()
        page.goto(f"{console.url}/instance/organizations")
        page.get_by_role("button", name="New Organization", exact=True).click()
        dialog = page.get_by_role("dialog", name="Create Organization", exact=True)
        dialog.get_by_role("button", name="Create Organization", exact=True).click()
        expect(dialog.get_by_text("Name is required", exact=True)).to_be_visible()
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).not_to_be_visible()
        page.get_by_role("button", name="New Organization", exact=True).click()
        dialog.get_by_label("Name", exact=True).fill("Created in browser")
        dialog.get_by_role("button", name="Create Organization", exact=True).click()
        expect(page.get_by_role("row").filter(has_text="Created in browser")).to_be_visible()
        page.get_by_role("button", name="Sign out", exact=True).click()
        expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
        expect(page.get_by_role("row").filter(has_text="Created in browser")).to_have_count(0)
        console.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible()


@pytest.mark.parametrize("role", ["admin", "member"])
def test_organization_roles_navigation_permissions_and_workspace_dialog(stack: Stack, role: str) -> None:
    with (
        running_console(stack) as console,
        httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "fetch"}) as admin,
        httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "fetch"}) as member,
    ):
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        org_path = f"/api/v1/orgs/{stack.org_id}"
        workspace = admin.get(f"{org_path}/workspaces").json()["data"][0]
        user_id = invite_member(admin, member, org_path, workspace["id"])
        admin.put(f"{org_path}/users/{user_id}", json={"role": role}).raise_for_status()
        admin.put(f"{org_path}/workspaces/{workspace['id']}/members/{user_id}", json={"role": "member"}).raise_for_status()
        console.login("browser-member@acceptance.test", "browser-member-password")
        page = console.page
        expect(page.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("acceptance")
        page.reload()
        expect(page.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text("acceptance")
        page.goto(f"{console.url}/instance/users")
        expect(page).to_have_url(re.compile(r"/org(?:/|$)"))
        expect(page.get_by_role("navigation", name="Instance navigation", exact=True)).to_have_count(0)
        assert console.context.request.get(f"{console.url}/api/v1/users", headers={"X-Requested-With": "fetch"}).status == 403
        page.goto(f"{console.url}/org/settings")
        if role == "member":
            expect(page.get_by_text("You do not have access to this organization page.", exact=True)).to_be_visible()
            assert console.context.request.get(f"{console.url}{org_path}/management-keys", headers={"X-Requested-With": "fetch"}).status == 403
        else:
            expect(page.get_by_role("button", name="Generate Key", exact=True)).to_be_visible()
        page.goto(f"{console.url}/org/workspaces/acceptance")
        page.get_by_role("combobox", name="Workspace", exact=True).click()
        page.get_by_role("option", name="Create Workspace", exact=True).click()
        dialog = page.get_by_role("dialog", name="New Workspace", exact=True)
        dialog.get_by_label("Name", exact=True).fill(f"{role}-workspace")
        dialog.get_by_role("button", name="Create", exact=True).click()
        expect(page.get_by_role("combobox", name="Workspace", exact=True)).to_contain_text(f"{role}-workspace")


def test_playground_streaming_errors_and_recovery(stack: Stack) -> None:
    with running_console(stack) as console:
        console.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        page = console.page
        page.get_by_role("link", name="Playground", exact=True).click()
        composer = page.get_by_placeholder("Send a message... (Shift+Enter for newline)")
        composer.fill("streaming browser probe")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.get_by_role("button", name="Stop generation", exact=True)).to_be_visible()
        expect(page.get_by_text("tick29", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="Stop generation", exact=True)).not_to_be_visible()
        page.get_by_role("button", name="Clear conversation", exact=True).click()
        page.get_by_role("switch", name="Streaming", exact=True).uncheck()
        composer.fill("malformed-buffered")
        with page.expect_response(lambda response: "/inf/" in response.url) as failed:
            page.get_by_role("button", name="Send message", exact=True).click()
        assert failed.value.status >= 400
        expect(page.get_by_text("Request failed", exact=True)).to_be_visible()
        composer.fill("recovered browser probe")
        page.get_by_role("button", name="Send message", exact=True).click()
        expect(page.get_by_text("ok", exact=True)).to_be_visible()
        expect(page.get_by_text("Request failed", exact=True)).to_have_count(0)
