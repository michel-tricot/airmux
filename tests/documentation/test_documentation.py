from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
DOCS = ROOT / "docs"
FENCE = re.compile(r"^[ \t]*```(?P<language>[A-Za-z0-9_+-]+)[^\n]*\n(?P<body>.*?)^[ \t]*```[ \t]*$", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"(?<!!)\[[^\]]+\]\((/docs(?:/[^)#?]+)?)(?:#[^)]+)?\)")
CURL_JSON = re.compile(r"(?:-d|--data)\s+'(?P<body>\{.*?\})'", re.DOTALL)


def documentation_files() -> list[Path]:
    return sorted([*DOCS.rglob("*.md"), *DOCS.rglob("*.mdx")])


def navigation_pages(node: object) -> list[str]:
    if isinstance(node, dict):
        raw_pages = node.get("pages")
        pages = [str(page) for page in raw_pages] if isinstance(raw_pages, list) else []
        return pages + [page for key, value in node.items() if key != "pages" for page in navigation_pages(value)]
    if isinstance(node, list):
        return [page for value in node for page in navigation_pages(value)]
    return []


def route_exists(route: str) -> bool:
    relative = route.removeprefix("/docs").strip("/")
    candidates = (
        DOCS / f"{relative}.md",
        DOCS / f"{relative}.mdx",
        DOCS / relative / "index.md",
        DOCS / relative / "index.mdx",
    )
    return any(candidate.exists() for candidate in candidates)


def test_navigation_references_existing_pages() -> None:
    config = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    pages = navigation_pages(config["navigation"])
    missing = [page for page in pages if not any((ROOT / f"{page}{suffix}").exists() for suffix in (".md", ".mdx"))]
    assert missing == []
    assert len(pages) == len(set(pages))


def test_internal_documentation_links_resolve() -> None:
    missing = [
        f"{path.relative_to(ROOT)}: {route}"
        for path in [ROOT / "README.md", *documentation_files()]
        for route in LINK.findall(path.read_text(encoding="utf-8"))
        if not route_exists(route)
    ]
    assert missing == []


@pytest.mark.parametrize("path", documentation_files(), ids=lambda path: str(path.relative_to(ROOT)))
def test_documentation_code_blocks_are_syntactically_valid(path: Path) -> None:
    for match in FENCE.finditer(path.read_text(encoding="utf-8")):
        language = match.group("language")
        body = match.group("body")
        if language == "python":
            ast.parse(body)
        elif language == "json":
            json.loads(body)
        elif language in {"bash", "sh"}:
            result = subprocess.run(["/bin/bash", "-n"], input=body, text=True, capture_output=True, check=False)
            assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("path", documentation_files(), ids=lambda path: str(path.relative_to(ROOT)))
def test_curl_request_bodies_are_valid_json(path: Path) -> None:
    for match in CURL_JSON.finditer(path.read_text(encoding="utf-8")):
        json.loads(match.group("body"))


def test_documentation_does_not_name_comparison_products() -> None:
    forbidden = re.compile(r"openrouter|litellm", re.IGNORECASE)
    occurrences = [str(path.relative_to(ROOT)) for path in [ROOT / "README.md", *documentation_files()] if forbidden.search(path.read_text())]
    assert occurrences == []


def test_quickstart_runs_the_project_cli_against_the_public_url() -> None:
    documents = "\n".join(path.read_text(encoding="utf-8") for path in [ROOT / "README.md", *documentation_files()])
    commands = re.findall(r"^uv run --package cli --no-dev --frozen airllm quickstart --url \S+$", documents, re.MULTILINE)

    assert commands
    assert "docker compose run" not in documents
    assert "--connect-url" not in documents


def test_runnable_examples_use_the_public_inference_prefix() -> None:
    sources = {path: path.read_text(encoding="utf-8") for path in (ROOT / "examples").glob("*.py")}
    assert all("/v1/chat/completions" not in source.replace("/inf/v1/chat/completions", "") for source in sources.values())
    assert "/inf" in sources[ROOT / "examples" / "anthropic_sdk.py"]
