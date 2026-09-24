from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml
from gateway_harness import eventually
from tests.documentation.examples import code_block
from upstream import TEXT, UPSTREAM_KEY


@pytest.mark.parametrize("document", ["README.md", "docs/deployment/gateway.mdx"])
def test_documented_gateway_initialization_and_curl(gateway, document):
    upstream = gateway.add_provider()
    environment = {
        "PATH": f"{Path(gateway.executable).parent}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(gateway.directory),
        "OPENAI_API_KEY": UPSTREAM_KEY,
    }
    initialize, serve = code_block(document, "airmux gateway init").split("airmux gateway serve")
    initialize = initialize.removeprefix("uv tool install airmux\n").replace("'your-provider-key'", shlex.quote(UPSTREAM_KEY))
    subprocess.run(["/bin/bash", "-eu", "-c", initialize], cwd=gateway.directory, env=environment, check=True, capture_output=True)  # noqa: S603 trusted documentation with local fixture credentials
    directory = gateway.directory
    taxonomy_path = directory / ".airmux/taxonomy.yml"
    taxonomy = yaml.safe_load(taxonomy_path.read_text())
    for provider in taxonomy["providers"]:
        provider["base_url"] = upstream.url
    taxonomy_path.write_text(yaml.safe_dump(taxonomy))
    gateway.sensitive_values = ((directory / ".airmux/inference.key").read_text().strip(),)
    gateway.process = subprocess.Popen(  # noqa: S603 execute the documented serve command with a dynamic local port
        [gateway.executable, "gateway", "serve", *shlex.split(serve), "--port", "0"],
        cwd=directory,
        env=environment,
        stdout=gateway.log,
        stderr=subprocess.STDOUT,
    )
    eventually(gateway.ready)
    request = code_block("docs/deployment/gateway.mdx", "curl --fail-with-body").replace("http://127.0.0.1:8080", gateway.url)
    result = subprocess.run(  # noqa: S603 execute the documented curl against the local gateway
        ["/bin/bash", "-eu", "-c", request],
        cwd=gateway.directory,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    readiness, end = json.JSONDecoder().raw_decode(result.stdout)
    assert readiness == {"status": "ready"}
    completion = json.loads(result.stdout[end:])
    assert completion["choices"][0]["message"]["content"] == TEXT
    assert len(upstream.requests) == 1
