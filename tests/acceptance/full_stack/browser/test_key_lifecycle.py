from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from browser_support import running_console
from playwright.sync_api import expect
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from stack_harness import Stack


def test_management_key_is_self_owned_shown_once_and_revoked(stack: Stack) -> None:
    with running_console(stack) as console:
        console.login(ADMIN_EMAIL, ADMIN_PASSWORD)
        page = console.page
        page.goto(f"{console.url}/instance/management-keys")
        page.get_by_role("button", name="Generate Key", exact=True).click()
        dialog = page.get_by_role("dialog", name="Generate Management Key")
        expect(dialog.get_by_label("User", exact=True)).to_have_count(0)
        expect(dialog.get_by_label("Principal", exact=True)).to_have_count(0)
        dialog.get_by_label("Label", exact=True).fill("browser-lifecycle")
        dialog.get_by_role("checkbox", name="catalog.read", exact=True).click()
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith("/instance/management-keys")
        ) as minted:
            dialog.get_by_role("button", name="Generate", exact=True).click()
        assert minted.value.status == 200
        key = minted.value.json()["data"]
        submitted = minted.value.request.post_data_json
        assert isinstance(submitted, dict)
        assert "user_id" not in submitted
        me = console.context.request.get(f"{console.url}/api/v1/auth/me", headers={"X-Requested-With": "XMLHttpRequest"}).json()["data"]
        assert key["user_id"] == me["user_id"]
        secret = page.get_by_label("Key Secret", exact=True)
        expect(secret).to_have_value(key["token"])
        page.get_by_role("button", name="Copy key", exact=True).click()
        assert page.evaluate("navigator.clipboard.readText()") == key["token"]
        page.get_by_role("button", name="I have saved it", exact=True).click()
        expect(secret).to_have_count(0)
        expect(page.get_by_role("row").filter(has_text="browser-lifecycle")).to_be_visible()
        headers = {"authorization": f"Bearer {key['token']}"}
        assert httpx.get(f"{stack.cp_url}/api/v1/auth/me", headers=headers).status_code == 200
        with page.expect_response(
            lambda response: response.request.method == "GET" and response.url.endswith("/instance/management-keys")
        ) as fetched:
            page.reload()
        assert key["token"] not in fetched.value.text()
        expect(page.get_by_label("Key Secret", exact=True)).to_have_count(0)
        assert key["token"] not in page.content()
        page.get_by_role("button", name="Revoke browser-lifecycle", exact=True).click()
        page.get_by_role("button", name="Revoke key", exact=True).click()
        expect(page.get_by_role("row").filter(has_text="browser-lifecycle")).to_contain_text("REVOKED")
        assert httpx.get(f"{stack.cp_url}/api/v1/auth/me", headers=headers).status_code == 401
