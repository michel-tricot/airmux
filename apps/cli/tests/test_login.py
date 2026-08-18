from __future__ import annotations

import httpx
import pytest
import respx
from typer.testing import CliRunner

from cli.main import app
from cli.profiles import active_profile, upsert_profile

runner = CliRunner()


@pytest.mark.parametrize("split_option", ["--control-plane-url", "--console-url"])
def test_login_url_is_exclusive_with_split_urls(split_option):
    result = runner.invoke(app, ["login", "--url", "https://airllm.example.com", split_option, "https://other.example.com"])

    assert result.exit_code == 2
    assert "--url cannot be combined" in result.output
    assert "--control-plane-url" in result.output
    assert "--console-url" in result.output


@pytest.mark.parametrize(
    ("stored_url", "expected_authorization"),
    [("https://cp.example", "Bearer sk-cp-old"), ("https://other.example", None)],
)
@respx.mock
def test_login_only_presents_the_current_control_planes_existing_key(tmp_path, monkeypatch, stored_url, expected_authorization):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setattr("cli.auth.time.sleep", lambda _: None)
    upsert_profile(
        "old",
        {
            "control_plane_url": stored_url,
            "console_url": "https://console.example",
            "org_id": "old-org",
            "org_name": "old",
            "token": "sk-cp-old",
        },
    )
    respx.post("https://cp.example/api/v1/auth/cli/start").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "user_code": "ABCD-EFGH",
                    "verification_url": "https://console.example/cli?code=ABCD-EFGH",
                    "poll_secret": "sk-cli-poll",
                    "interval_seconds": 0,
                    "expires_in_seconds": 30,
                }
            },
        )
    )
    poll = respx.post("https://cp.example/api/v1/auth/cli/poll").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "status": "complete",
                    "interval_seconds": 0,
                    "token": "sk-cp-new",
                    "org_id": "new-org",
                    "org_name": "new",
                }
            },
        )
    )

    result = runner.invoke(app, ["login", "--url", "https://cp.example", "--no-browser"])

    assert result.exit_code == 0, result.output
    assert poll.calls.last.request.headers.get("authorization") == expected_authorization
    profile = active_profile()
    assert profile is not None
    assert profile["control_plane_url"] == "https://cp.example"
    assert profile["console_url"] == "https://cp.example"
