from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest

FAKE_CLI = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

state_path = Path(os.environ["BOOTSTRAP_TEST_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]
tool = Path(sys.argv[0]).name


def option(name):
    return args[args.index(name) + 1]


def finish(output=None):
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if output is not None:
        print(output)
    raise SystemExit


if tool == "flyctl":
    if args[:2] == ["orgs", "list"]:
        finish(json.dumps({"personal": "Personal"}))
    if args[:2] == ["apps", "list"]:
        finish(json.dumps([{"Name": name} for name in state["apps"]]))
    if args[:2] == ["apps", "create"]:
        state["apps"].append(args[2])
        finish()
    if args[:2] == ["mpg", "list"]:
        clusters = [
            {
                "id": cluster["id"],
                "name": cluster["name"],
                "status": "ready",
                "attached_apps": [{"name": name} for name in state["attachments"]],
            }
            for cluster in state["clusters"]
        ]
        finish(json.dumps(clusters))
    if args[:2] == ["mpg", "create"]:
        state["clusters"].append({"id": "cluster-1", "name": option("--name")})
        finish()
    if args[:2] == ["mpg", "status"]:
        finish(
            json.dumps(
                {
                    "data": {"id": args[2], "status": "ready"},
                    "credentials": {
                        "pgbouncer_uri": "postgresql://user:password@pgbouncer.cluster.internal/database",
                    },
                }
            )
        )
    if args[:2] == ["mpg", "attach"]:
        state["attachments"] = [option("--app")]
        finish()
    if args[:2] == ["secrets", "import"]:
        state["fly_secrets"][option("--app")] = dict(line.split("=", 1) for line in sys.stdin.read().splitlines())
        finish()
    if args[:3] == ["tokens", "create", "deploy"]:
        app = option("--app")
        state["tokens"].append(app)
        finish(f"FlyV1 token-{app}")
    if args and args[0] == "deploy":
        state["deploys"].append(option("--app"))
        finish()

if tool == "gh":
    if args[:2] == ["repo", "view"]:
        finish(json.dumps({"nameWithOwner": "owner/repo"}))
    if args and args[0] == "api":
        state["environment"] = True
        finish()
    if args[:2] == ["secret", "list"]:
        finish(json.dumps([{"name": name} for name in state["github_secrets"]]))
    if args[:2] == ["secret", "set"]:
        state["github_secrets"][args[2]] = option("--body")
        finish()
    if args[:2] == ["variable", "set"]:
        state["variables"][args[2]] = option("--body")
        finish()

raise SystemExit(f"unexpected {tool} command: {args}")
"""


@pytest.mark.parametrize("config_name", ["backend.toml", "console.toml"])
def test_fly_dockerfile_exists_relative_to_config(config_name):
    config_path = Path(__file__).resolve().parents[3] / "deploy" / "fly" / config_name
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert (config_path.parent / config["build"]["dockerfile"]).is_file()


def test_fly_workflow_uses_node_24_checkout():
    workflow_path = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-fly.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert workflow.count("uses: actions/checkout@v6") == 2
    assert "uses: actions/checkout@v4" not in workflow


def test_fly_bootstrap_derives_names_and_is_idempotent(tmp_path):
    repo = Path(__file__).resolve().parents[3]
    state_path = tmp_path / "state.json"
    initial_state = {
        "apps": [],
        "attachments": [],
        "clusters": [],
        "deploys": [],
        "environment": False,
        "fly_secrets": {},
        "github_secrets": {},
        "tokens": [],
        "variables": {},
    }
    state_path.write_text(json.dumps(initial_state), encoding="utf-8")
    for name in ("flyctl", "gh"):
        command = tmp_path / name
        command.write_text(FAKE_CLI, encoding="utf-8")
        command.chmod(0o755)
    env = {
        **os.environ,
        "BOOTSTRAP_TEST_STATE": str(state_path),
        "FLYCTL": str(tmp_path / "flyctl"),
        "GH": str(tmp_path / "gh"),
    }
    bootstrap = repo / "deploy" / "fly" / "bootstrap.sh"

    for _ in range(2):
        subprocess.run([bootstrap, "acme"], cwd=repo, env=env, check=True, capture_output=True, text=True)  # noqa: S603 trusted repository script

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["apps"] == ["acme-backend", "acme-frontend"]
    assert state["clusters"] == [{"id": "cluster-1", "name": "acme"}]
    assert state["attachments"] == ["acme-backend"]
    assert state["environment"] is True
    assert state["fly_secrets"] == {
        "acme-backend": {
            "DATABASE_URL": "postgresql://user:password@pgbouncer.cluster.internal/database",
            "DIRECT_DATABASE_URL": "postgresql://user:password@direct.cluster.internal/database",
        }
    }
    assert state["tokens"] == ["acme-backend", "acme-frontend"]
    assert state["github_secrets"].keys() == {"FLY_BACKEND_API_TOKEN", "FLY_CONSOLE_API_TOKEN"}
    assert state["variables"] == {
        "AIRLLM_PUBLIC_URL": "https://acme-frontend.fly.dev",
        "FLY_BACKEND_APP": "acme-backend",
        "FLY_CONSOLE_APP": "acme-frontend",
        "FLY_REGION": "sjc",
    }
    assert state["deploys"] == ["acme-backend", "acme-frontend", "acme-backend", "acme-frontend"]
