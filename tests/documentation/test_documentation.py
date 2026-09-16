from __future__ import annotations

import ast
import json
import re
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).parents[2]
DOCS = ROOT / "docs"
FENCE = re.compile(r"^[ \t]*```(?P<language>[A-Za-z0-9_+-]+)[^\n]*\n(?P<body>.*?)^[ \t]*```[ \t]*$", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"(?<!!)\[[^\]]+\]\((/docs(?:/[^)#?]+)?)(?:#[^)]+)?\)")
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]+\]\((?!https?://|mailto:|#)(?P<target>[^)#?]+)(?:#[^)]+)?\)")
CURL_JSON = re.compile(r"(?:-d|--data)\s+'(?P<body>\{.*?\})'", re.DOTALL)
OPENAPI_ENDPOINT = re.compile(r"^(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE) /\S+$")
PUBLIC_REPOSITORY = "https://github.com/michel-tricot/airmux"
PUBLISHED_PROJECT = ROOT / "packaging/airmux/pyproject.toml"
INTERNAL_DISTRIBUTIONS = {
    "airmux-api-models",
    "airmux-contract",
    "airmux-control-plane",
    "airmux-data-plane",
    "airmux-runtime",
}
BUNDLED_PROJECTS = (
    "apps/cli/pyproject.toml",
    "apps/control-plane/pyproject.toml",
    "apps/data-plane/pyproject.toml",
    "lib/api-models/pyproject.toml",
    "lib/contract/pyproject.toml",
    "lib/runtime/pyproject.toml",
)


def documentation_files() -> list[Path]:
    return sorted([ROOT / "CONTRIBUTING.md", *DOCS.rglob("*.md"), *DOCS.rglob("*.mdx")])


def navigation_pages(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [page for value in node.values() if isinstance(value, (dict, list)) for page in navigation_pages(value)]
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
    pages = [page for page in navigation_pages(config["navigation"]) if not OPENAPI_ENDPOINT.fullmatch(page)]
    missing = [page for page in pages if not any((ROOT / f"{page}{suffix}").exists() for suffix in (".md", ".mdx"))]
    assert missing == []
    assert len(pages) == len(set(pages))


def test_api_navigation_follows_openapi_domains_and_resources() -> None:
    config = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    api_group = next(group for tab in config["navigation"]["tabs"] for group in tab["groups"] if group["group"] == "Control plane endpoints")
    documented = [
        (domain["group"], resource["group"], endpoint)
        for domain in api_group["pages"]
        for resource in domain["pages"]
        for endpoint in resource["pages"]
    ]
    schema = yaml.safe_load((ROOT / "lib/api-spec/openapi.yaml").read_text(encoding="utf-8"))
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    domains = {tag: group["name"] for group in schema["x-tagGroups"] for tag in group["tags"]}
    resources = {tag["name"]: tag.get("x-displayName", tag["name"]) for tag in schema["tags"]}
    expected = [
        (domains[tag], resources[tag], f"{method.upper()} {path}")
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in methods
        for tag in operation["tags"]
    ]

    assert Counter(documented) == Counter(expected)


def test_internal_documentation_links_resolve() -> None:
    missing = [
        f"{path.relative_to(ROOT)}: {route}"
        for path in [ROOT / "README.md", *documentation_files()]
        for route in LINK.findall(path.read_text(encoding="utf-8"))
        if not route_exists(route)
    ]
    assert missing == []


def test_contributor_documentation_has_a_repository_entry_point() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    contributing_path = ROOT / "CONTRIBUTING.md"
    design_index_path = ROOT / "notes" / "design" / "README.md"

    assert contributing_path.exists()
    assert design_index_path.exists()
    assert "[Contributing](CONTRIBUTING.md)" in readme

    contributing = contributing_path.read_text(encoding="utf-8")
    assert "docs/development.mdx" in contributing
    assert "notes/design/README.md" in contributing


def test_documentation_tracks_current_ci_entry_points() -> None:
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    development = (DOCS / "development.mdx").read_text(encoding="utf-8")

    assert "tests/ci/test_merge_policy.py" in contributing
    assert "tests/documentation/test_merge_policy.py" not in contributing
    assert "uv run pytest tests/ci tests/documentation tests/workflows -q" in development
    assert "Prepare release" in development
    assert "Publish release" in development
    assert "prefilled pull request link" in development


def test_documentation_covers_safe_upgrades() -> None:
    assert (DOCS / "deployment" / "upgrades.mdx").exists()


def test_readme_is_a_complete_oss_entry_point() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    expected_badges = (
        "actions/workflows/ci.yml/badge.svg",
        "img.shields.io/pypi/v/airmux",
        "img.shields.io/badge/python-3.13%2B",
        "img.shields.io/badge/license-Elastic--2.0",
    )
    quickstart_commands = (
        "uv tool install airmux",
        "airmux gateway init",
        "airmux gateway serve",
        "/inf/v1/chat/completions",
    )
    headings = re.findall(r"^## (.+)$", readme, re.MULTILINE)

    assert all(badge in readme for badge in expected_badges)
    assert all(command in readme for command in quickstart_commands)
    assert "Any client that can target one of airmux's exposed HTTP APIs" in readme
    assert "x-airmux-dialect: openai_native" not in readme.lower()
    assert headings.index("Quickstart") < headings.index("Architecture")


def test_public_links_use_the_current_repository() -> None:
    stale_repository = "https://github.com/michel-tricot/airllm"
    public_documents = [ROOT / "README.md", *documentation_files()]
    occurrences = [str(path.relative_to(ROOT)) for path in public_documents if stale_repository in path.read_text()]

    assert occurrences == []


def test_airmux_is_the_only_published_python_distribution() -> None:
    project = tomllib.loads(PUBLISHED_PROJECT.read_text(encoding="utf-8"))["project"]

    assert project["name"] == "airmux"
    assert project["description"]
    assert project["urls"]["Repository"] == PUBLIC_REPOSITORY
    dependencies = {re.split(r"[\[<>=!~]", dependency, maxsplit=1)[0] for dependency in project["dependencies"]}
    assert dependencies.isdisjoint(INTERNAL_DISTRIBUTIONS)


def bundled_projects() -> dict[str, dict[str, object]]:
    return {path: tomllib.loads((ROOT / path).read_text(encoding="utf-8"))["project"] for path in BUNDLED_PROJECTS}


def project_dependencies(project: dict[str, object]) -> list[str]:
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    return [str(dependency) for dependency in dependencies]


def merged_requirements(dependencies: list[str]) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    requirements = [Requirement(dependency) for dependency in dependencies]
    return {
        name: (
            frozenset(extra for requirement in requirements if canonicalize_name(requirement.name) == name for extra in requirement.extras),
            frozenset(
                str(specifier) for requirement in requirements if canonicalize_name(requirement.name) == name for specifier in requirement.specifier
            ),
        )
        for name in {canonicalize_name(requirement.name) for requirement in requirements}
    }


def test_published_dependencies_match_the_bundled_projects() -> None:
    published = tomllib.loads(PUBLISHED_PROJECT.read_text(encoding="utf-8"))["project"]["dependencies"]
    bundled = [
        dependency
        for project in bundled_projects().values()
        for dependency in project_dependencies(project)
        if canonicalize_name(Requirement(dependency).name) not in INTERNAL_DISTRIBUTIONS
    ]

    assert merged_requirements(published) == merged_requirements(bundled)


def test_bundled_projects_are_release_independent() -> None:
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["uv"]["sources"]
    for path, project in bundled_projects().items():
        assert project["version"] == "0.0.0", path
        internal_requirements = [
            Requirement(dependency)
            for dependency in project_dependencies(project)
            if canonicalize_name(Requirement(dependency).name) in INTERNAL_DISTRIBUTIONS
        ]
        for requirement in internal_requirements:
            assert not requirement.specifier, (path, requirement.name)
            assert sources[requirement.name] == {"workspace": True}, (path, requirement.name)


@pytest.mark.parametrize("path", [ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "notes" / "design" / "README.md"])
def test_repository_documentation_links_resolve(path: Path) -> None:
    missing = [target for target in LOCAL_LINK.findall(path.read_text(encoding="utf-8")) if not (path.parent / target).resolve().exists()]
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


def test_public_examples_use_a_neutral_smoke_prompt() -> None:
    documents = "\n".join(path.read_text(encoding="utf-8") for path in [ROOT / "README.md", *documentation_files()])
    assert "Reply with exactly: airmux ready" not in documents
    assert "Say hello in one word." in documents


def test_documentation_does_not_name_comparison_products() -> None:
    forbidden = re.compile(r"openrouter|litellm", re.IGNORECASE)
    occurrences = [str(path.relative_to(ROOT)) for path in [ROOT / "README.md", *documentation_files()] if forbidden.search(path.read_text())]
    assert occurrences == []


def test_quickstart_runs_the_installed_cli_against_the_public_url() -> None:
    documents = "\n".join(path.read_text(encoding="utf-8") for path in [ROOT / "README.md", *documentation_files()])
    commands = re.findall(r"^\s*airmux quickstart --url \S+$", documents, re.MULTILINE)

    assert commands
    assert "docker compose run" not in documents
    assert "--connect-url" not in documents


def test_runnable_examples_use_the_public_inference_prefix() -> None:
    sources = {path: path.read_text(encoding="utf-8") for path in (ROOT / "examples").glob("*.py")}
    assert all("/v1/chat/completions" not in source.replace("/inf/v1/chat/completions", "") for source in sources.values())
    assert "/inf" in sources[ROOT / "examples" / "anthropic_sdk.py"]


def test_canonical_examples_do_not_require_a_dialect_override() -> None:
    paths = [ROOT / "README.md", *documentation_files(), *(ROOT / "notes").rglob("*.md"), *(ROOT / "examples").rglob("*.py")]
    override = re.compile(r"x-airmux-dialect[\"']?\s*:\s*[\"']?canonical", re.IGNORECASE)
    assert [str(path.relative_to(ROOT)) for path in paths if override.search(path.read_text(encoding="utf-8"))] == []
