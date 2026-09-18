from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import httpx
from stack_harness import ADMIN_EMAIL, ADMIN_PASSWORD


def test_documented_pagination_fetches_the_next_page(stack):
    stack.write_config()
    stack.start_cp()
    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10) as admin:
        admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}).raise_for_status()
        for number in range(50):
            admin.post("/api/v1/organizations", json={"name": f"pagination-{number}"}).raise_for_status()
        organizations = admin.get("/api/v1/organizations", params={"limit": 200})
        organizations.raise_for_status()
        management_key = admin.post(
            "/api/v1/instance/management-keys",
            json={"label": "documented-pagination", "permissions": ["organizations.read"]},
        )
        management_key.raise_for_status()

    document = (Path(__file__).parents[4] / "docs/reference/management-api.mdx").read_text(encoding="utf-8")
    examples = re.findall(r"```bash\n(.*?)```", document, re.DOTALL)
    first_command, next_command = next(example for example in examples if "$NEXT_CURSOR" in example).strip().split("\n\n")

    def fetch_page(command, cursor=""):
        result = subprocess.run(
            ["/bin/bash"],
            input=command.replace("https://llm.example.com", stack.cp_url),
            env={**os.environ, "AIRMUX_MANAGEMENT_KEY": management_key.json()["data"]["token"], "NEXT_CURSOR": cursor},
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        page = json.loads(result.stdout)
        assert "data" in page, page
        return page

    first_page = fetch_page(first_command)
    cursor = first_page["page"]["next_cursor"]
    assert cursor
    next_page = fetch_page(next_command, cursor)

    first_ids = {organization["id"] for organization in first_page["data"]}
    next_ids = {organization["id"] for organization in next_page["data"]}
    assert len(first_page["data"]) == 50
    assert next_ids
    assert first_ids.isdisjoint(next_ids)
    assert first_ids | next_ids == {organization["id"] for organization in organizations.json()["data"]}
    assert next_page["page"]["next_cursor"] is None
