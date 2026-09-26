from __future__ import annotations

import json
import re
import subprocess
import sys

from tests.documentation.examples import cli_reference_commands, code_block
from tests.documentation.test_documentation import ROOT
from typer.testing import CliRunner

from cli.main import app


def test_cli_reference_commands_exist():
    result = CliRunner().invoke(app, ["commands", "-f", "json"])
    assert result.exit_code == 0, result.output
    inventory = {command["command"] for command in json.loads(result.output)}
    assert cli_reference_commands() - inventory == set()


def test_replit_cli_examples_exist():
    commands = re.findall(r"\buv run airmux ([a-z-]+ [a-z-]+)", (ROOT / "replit.md").read_text())
    assert commands
    for command in commands:
        result = CliRunner().invoke(app, [*command.split(), "--help"])
        assert result.exit_code == 0, result.output
    script = code_block("replit.md", "./scripts/replit-backend.sh").strip()
    assert (ROOT / script).is_file()


def test_compose_recipe_uses_the_published_image():
    recipe = code_block("docs/quickstart.mdx", "curl -fsSLO")
    assert "releases/latest/download/docker-compose.yml" in recipe
    assert recipe.count("curl ") == 1
    assert ".env.example" not in recipe
    assert "docker build" not in recipe


def test_provider_source_example_is_discovered_and_maps_models(tmp_path):
    (tmp_path / "example.py").write_text(code_block("model-audit/README.md", "class Example(ModelSource)"))
    result = subprocess.run(  # noqa: S603 execute the repository's documented source in an isolated interpreter
        [
            sys.executable,
            "-c",
            """
import sys
from pathlib import Path
from model_audit.catalog_tasks import sources
from model_audit.catalog_tasks.sources import base

sources.__path__.append(sys.argv[1])
base.__file__ = str(Path(sys.argv[1]) / "base.py")
source = base.registry()["example"]
assert source.definition.id == source.provider_id == "example"
assert source.definition.models_url == source.url
assert source.schemas[0].url == source.definition.openapi
assert source.headers("fixture-key")["Authorization"] == "Bearer fixture-key"
models = [source.normalize(item) for item in source.items({"data": [
    {"id": "example-model", "context_length": 8192, "max_output_tokens": 512, "ignored": "value"}
]})]
assert models == [{
    "id": "example-model", "context_length": 8192, "max_output_tokens": 512,
    "input_modalities": None, "output_modalities": None,
    "supports_tools": None, "supports_structured_output": None, "pricing": None,
}], models
""",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
