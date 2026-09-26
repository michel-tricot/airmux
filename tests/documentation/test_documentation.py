from __future__ import annotations

import ast
import json
import re
import subprocess
import tomllib
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from typer.testing import CliRunner

from cli.main import app

ROOT = Path(__file__).parents[2]
DOCS = ROOT / "docs"
FENCE = re.compile(r"^[ \t]*```(?P<language>[A-Za-z0-9_+-]+)[^\n]*\n(?P<body>.*?)^[ \t]*```[ \t]*$", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"(?<!!)\[[^\]]+\]\((/docs(?:/[^)#?]+)?)(?:#[^)]+)?\)")
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]+\]\((?!https?://|mailto:|#)(?P<target>[^)#?]+)(?:#[^)]+)?\)")
CURL_JSON = re.compile(r"(?:-d|--data)\s+'(?P<body>\{.*?\})'", re.DOTALL)
OPENAPI_ENDPOINT = re.compile(r"^(?:GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE) /\S+$")
PUBLIC_REPOSITORY = "https://github.com/michel-tricot/airmux"
REPOSITORY_SOURCE_LINK = re.compile(rf"(?<!!)\[[^\]]+\]\({re.escape(PUBLIC_REPOSITORY)}/(?:blob|tree)/main/(?P<target>[^)#?]+)(?:[?#][^)]*)?\)")
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
    return sorted([ROOT / "CONTRIBUTING.md", ROOT / ".github/policy/README.md", *DOCS.rglob("*.md"), *DOCS.rglob("*.mdx")])


def example_files() -> list[Path]:
    return sorted([ROOT / "README.md", ROOT / "model-audit/README.md", ROOT / "replit.md", *documentation_files()])


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
    policy = (ROOT / ".github/policy/README.md").read_text(encoding="utf-8")
    development = (DOCS / "development.mdx").read_text(encoding="utf-8")
    releasing = (DOCS / "releasing.mdx").read_text(encoding="utf-8")

    assert "tests/ci/test_merge_policy.py" in policy
    assert "tests/documentation/test_merge_policy.py" not in policy
    assert "uv run pytest -n auto" in development
    assert "/docs/releasing" in development
    assert "Prepare Release" in releasing
    assert "Publish Release" in releasing


def test_documentation_covers_safe_upgrades() -> None:
    for page in ("docker.mdx", "without-docker.mdx", "scaling.mdx", "gateway.mdx"):
        assert "## Upgrade and roll back" in (DOCS / "deployment" / page).read_text(encoding="utf-8")


def test_documented_cli_command_groups_and_subcommands_exist() -> None:
    reference = (DOCS / "reference" / "cli.mdx").read_text(encoding="utf-8")
    groups = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*(`[^|]+)\|$", reference, re.MULTILINE)
    assert groups
    runner = CliRunner()

    for group, commands in groups:
        for command in (group, *(f"{group} {name}" for name in re.findall(r"`([^`]+)`", commands))):
            result = runner.invoke(app, [*command.split(), "--help"])
            assert result.exit_code == 0, f"Documented command 'airmux {command}' failed:\n{result.output}"


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
    assert headings.index("Quickstart") < headings.index("Architecture")


def test_readme_leads_with_the_full_platform() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.index("docker compose up -d --wait") < readme.index("airmux gateway init")
    assert readme.index("airmux quickstart --url") < readme.index("airmux gateway serve")

    headings = re.findall(r"^## (.+)$", readme, re.MULTILINE)
    assert headings.index("Quickstart") < headings.index("Gateway-only mode")


def test_every_entry_point_recommends_the_same_quickstart() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    homepage = (DOCS / "index.mdx").read_text(encoding="utf-8")
    config = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    documentation = next(tab for tab in config["navigation"]["tabs"] if tab["tab"] == "Documentation")
    first_group = documentation["groups"][0]

    assert "docs/quickstart.mdx" in readme
    assert "/docs/quickstart" in homepage
    assert first_group["pages"] == ["docs/index", "docs/quickstart"]


def test_documentation_navigation_is_organized_around_reader_tasks() -> None:
    config = json.loads((ROOT / "docs.json").read_text(encoding="utf-8"))
    documentation = next(tab for tab in config["navigation"]["tabs"] if tab["tab"] == "Documentation")

    assert [group["group"] for group in documentation["groups"]] == [
        "Get started",
        "Use the platform",
        "Deploy and operate",
        "Concepts",
        "Contributing",
    ]


def test_full_platform_instructions_download_the_release_compose_file() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    quickstart = (DOCS / "quickstart.mdx").read_text(encoding="utf-8")
    for document in (readme, quickstart):
        assert "releases/latest/download/docker-compose.yml" in document
        assert "docker compose exec cli airmux quickstart" in document


def test_quickstart_walks_through_the_webapp_and_links_to_customization() -> None:
    quickstart = (DOCS / "quickstart.mdx").read_text(encoding="utf-8")

    assert "airmux quickstart --url" in quickstart
    assert "/inf/v1" in quickstart
    assert "/docs/guides/policies#create-a-workspace-policy" in quickstart
    assert "/docs/deployment/docker#customize-the-runtime-yaml" in quickstart
    assert "docker compose down" in quickstart

    steps = re.findall(r'<Step title="([^"]+)">', quickstart)
    assert steps == ["Download the release's Compose file", "Start and claim the instance", "See the request"]


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


@pytest.mark.parametrize(
    "path",
    [ROOT / path for path in ("README.md", "CONTRIBUTING.md", "notes/design/README.md", "notes/design/CI.md", ".github/policy/README.md")],
)
def test_repository_documentation_links_resolve(path: Path) -> None:
    missing = [target for target in LOCAL_LINK.findall(path.read_text(encoding="utf-8")) if not (path.parent / target).resolve().exists()]
    assert missing == []


@pytest.mark.parametrize("path", [ROOT / "notes/design/README.md", *example_files()], ids=lambda path: str(path.relative_to(ROOT)))
def test_repository_source_links_resolve(path: Path) -> None:
    missing = [target for target in REPOSITORY_SOURCE_LINK.findall(path.read_text(encoding="utf-8")) if not (ROOT / unquote(target)).exists()]
    assert missing == []


@pytest.mark.parametrize("path", example_files(), ids=lambda path: str(path.relative_to(ROOT)))
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


@pytest.mark.parametrize("path", example_files(), ids=lambda path: str(path.relative_to(ROOT)))
def test_curl_request_bodies_are_valid_json(path: Path) -> None:
    for match in CURL_JSON.finditer(path.read_text(encoding="utf-8")):
        json.loads(match.group("body"))


def test_quickstart_runs_the_image_cli() -> None:
    documents = "\n".join(path.read_text(encoding="utf-8") for path in [ROOT / "README.md", *documentation_files()])
    commands = re.findall(r"^\s*docker compose exec cli airmux quickstart --url http://localhost:8080$", documents, re.MULTILINE)

    assert commands
    assert "docker compose run" not in documents


def test_runnable_examples_use_the_public_inference_prefix() -> None:
    sources = {path: path.read_text(encoding="utf-8") for path in (ROOT / "examples").glob("*.py")}
    assert all("/v1/chat/completions" not in source.replace("/inf/v1/chat/completions", "") for source in sources.values())
    assert "/inf" in sources[ROOT / "examples" / "anthropic_sdk.py"]
