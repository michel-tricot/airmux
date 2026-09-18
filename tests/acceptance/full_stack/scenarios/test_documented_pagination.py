from __future__ import annotations

import json
import subprocess

import httpx
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD
from tests.documentation.examples import code_block


def test_documented_curl_fetches_the_next_organization_page(stack):
    stack.write_config()
    stack.start_cp()
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}) as owner:
        owner.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        for name in ("docs-first", "docs-second"):
            owner.post("/api/v1/organizations", json={"name": name}).raise_for_status()
        issued = owner.post("/api/v1/instance/management-keys", json={"label": "documentation", "permissions": ["organizations.read"]})
        assert issued.status_code == 200, issued.text
        token = issued.json()["data"]["token"]
    example = code_block("docs/reference/management-api.mdx", "$NEXT_CURSOR")
    first_command, second_command = example.strip().split("\n\n")
    environment = {**stack.env, "AIRMUX_MANAGEMENT_KEY": token}
    pages = []
    for example_command in (first_command, second_command):
        command = example_command.replace("https://llm.example.com", stack.cp_url).replace("limit=50", "limit=1")
        result = subprocess.run(  # noqa: S603 the documented curl targets the disposable control plane
            ["/bin/bash", "-eu", "-c", command],
            cwd=stack.tmp,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        page = json.loads(result.stdout)
        assert "data" in page, page
        assert len(page["data"]) == 1, page
        pages.append(page)
        environment = {**environment, "NEXT_CURSOR": page["page"]["next_cursor"]}
    assert pages[0]["page"]["next_cursor"]
    assert [page["data"][0]["name"] for page in pages] == ["docs-second", "docs-first"]
