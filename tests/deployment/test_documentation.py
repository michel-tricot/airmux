from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_quickstart_runs_the_project_cli_against_the_public_url():
    documents = "\n".join(document.read_text() for document in (ROOT / "README.md", *(ROOT / "docs").rglob("*.md")))
    commands = re.findall(r"^uv run --package cli --no-dev --frozen airllm quickstart --url \S+$", documents, re.MULTILINE)

    assert commands
    assert "docker compose run" not in documents
    assert "--connect-url" not in documents


def test_readme_links_one_click_deployments():
    readme = (ROOT / "README.md").read_text()

    assert "https://render.com/deploy?repo=https://github.com/michel-tricot/airllm" in readme
    assert re.search(r"https://railway\.com/new/template/[A-Za-z0-9_-]+", readme)
    assert "docs/deployment/railway.md" in readme
