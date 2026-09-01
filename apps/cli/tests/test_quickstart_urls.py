"""Which control plane and console the CLI talks to, and how --dev shortcuts them."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from typer.testing import CliRunner

from cli import auth
from cli.auth import DEFAULT_CONSOLE_URL, ProviderKey, configured_model, resolve_login_urls, resolve_urls, seed_provider_credentials
from cli.client import LOCAL_CONTROL_PLANE_URL, resolve_control_plane_url
from cli.common import invocation
from cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _plain_invocation():
    """--dev is state for the whole run, so a test that sets it has to put it back."""
    invocation.dev = False
    yield
    invocation.dev = False


@pytest.fixture
def _no_ambient_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))


@pytest.mark.usefixtures("_no_ambient_config")
def test_dev_names_the_local_control_plane():
    invocation.dev = True

    assert resolve_control_plane_url() == LOCAL_CONTROL_PLANE_URL


@pytest.mark.usefixtures("_no_ambient_config")
def test_an_explicit_url_beats_dev():
    """The flag is a shortcut, not an override of what the caller actually asked for."""
    invocation.dev = True

    assert resolve_control_plane_url("https://cp.example.com") == "https://cp.example.com"


def test_dev_beats_a_stored_profile(tmp_path, monkeypatch):
    """A development run must not be redirected by whatever org the machine last logged into."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    from cli.profiles import set_active, upsert_profile  # noqa: PLC0415 the profile has to be written under the patched path

    upsert_profile("prod", {"control_plane_url": "https://prod.example.com", "token": "t"})
    set_active("prod")

    assert resolve_control_plane_url() == "https://prod.example.com"
    invocation.dev = True
    assert resolve_control_plane_url() == LOCAL_CONTROL_PLANE_URL


@pytest.mark.usefixtures("_no_ambient_config")
def test_the_console_does_not_move_with_dev():
    """One console port everywhere, so the flag has nothing to switch."""
    invocation.dev = True

    assert resolve_urls("", "") == (LOCAL_CONTROL_PLANE_URL, DEFAULT_CONSOLE_URL)


@pytest.mark.usefixtures("_no_ambient_config")
def test_explicit_urls_win_over_everything():
    invocation.dev = True

    assert resolve_urls("https://cp.example.com", "https://console.example.com") == (
        "https://cp.example.com",
        "https://console.example.com",
    )


@pytest.mark.usefixtures("_no_ambient_config")
def test_login_url_uses_one_origin_for_the_control_plane_and_console():
    assert resolve_login_urls("https://airllm.example.com/", "", "") == (
        "https://airllm.example.com",
        "https://airllm.example.com",
    )


def test_a_checkout_config_is_not_a_source(tmp_path, monkeypatch):
    """airllm.yml configures the servers, not the CLI. Reading it would point a run at whatever
    checkout it happened to start in rather than at the deployment the user signed into."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONTROL_PLANE_URL", raising=False)
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))
    (tmp_path / "airllm.yml").write_text("data_plane:\n  control_plane:\n    url: http://somewhere.else:9999\n", encoding="utf-8")

    assert resolve_control_plane_url() == LOCAL_CONTROL_PLANE_URL


class QuickstartClient:
    def __init__(self, catalog: dict, credentials: list[dict]) -> None:
        self.catalog = catalog
        self.credentials = credentials
        self.posts: list[tuple[str, dict]] = []

    def get(self, path: str):
        data = self.catalog if path == "/api/v1/instance/taxonomy" else self.credentials
        return httpx.Response(200, request=httpx.Request("GET", f"http://control-plane{path}"), json={"data": data})

    def post(self, path: str, json: dict):
        self.posts.append((path, json))
        return httpx.Response(200, request=httpx.Request("POST", f"http://control-plane{path}"), json={"data": {"id": "credential"}})


def test_quickstart_keeps_an_existing_provider_credential(monkeypatch):
    monkeypatch.setattr("cli.auth._provider_key", lambda _name, _overrides: (_ for _ in ()).throw(AssertionError("must not prompt")))
    client = QuickstartClient(
        {"providers": [{"id": "provider-1", "name": "openai"}], "models": []},
        [{"provider_name": "openai", "enabled": True}],
    )

    result = seed_provider_credentials(cast("httpx.Client", client), {})

    assert result[0].provider == "openai"
    assert result[0].source == "already configured"
    assert client.posts == []


def test_quickstart_reports_an_existing_disabled_provider_credential(monkeypatch):
    monkeypatch.setattr("cli.auth._provider_key", lambda _name, _overrides: (_ for _ in ()).throw(AssertionError("must not prompt")))
    client = QuickstartClient(
        {"providers": [{"id": "provider-1", "name": "openai"}], "models": []},
        [{"provider_name": "openai", "enabled": False}],
    )

    result = seed_provider_credentials(cast("httpx.Client", client), {})

    assert result == [ProviderKey("openai", "already configured", "credential exists but is disabled")]
    assert client.posts == []


def test_quickstart_uses_a_model_backed_by_a_configured_provider():
    client = QuickstartClient(
        {
            "providers": [
                {"id": "provider-1", "name": "openai"},
                {"id": "provider-2", "name": "anthropic"},
            ],
            "models": [
                {"name": "anthropic/claude", "provider_id": "provider-2"},
                {"name": "openai/gpt", "provider_id": "provider-1"},
            ],
        },
        [{"provider_name": "anthropic", "enabled": True}],
    )

    assert configured_model(cast("httpx.Client", client)) == "anthropic/claude"


def test_quickstart_mints_an_access_key_without_replacing_the_active_one():
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        responses = {
            "/api/v1/auth/cli/start": {"user_code": "CODE", "poll_secret": "secret"},
            "/api/v1/auth/cli/approve": {},
            "/api/v1/auth/cli/poll": {"token": "new-token"},
        }
        return httpx.Response(200, json={"data": responses[request.url.path]})

    with httpx.Client(base_url="http://control-plane", transport=httpx.MockTransport(handle)) as client:
        token = auth._organization_access_key(client, "org-1")

    assert token == "new-token"
    poll = next(request for request in requests if request.url.path == "/api/v1/auth/cli/poll")
    assert "authorization" not in poll.headers


class QuickstartContext:
    def __init__(self, claimed: bool) -> None:
        self.claimed = claimed

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, path: str):
        assert path == "/api/v1/instance/oss/claim"
        return httpx.Response(200, request=httpx.Request("GET", f"http://control-plane{path}"), json={"data": {"claimed": self.claimed}})


def _quickstart(monkeypatch, *, claimed: bool, model: str | None, gateway_error: str = ""):
    context = QuickstartContext(claimed)
    login_calls = []
    saved = {}
    verified = []
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: context)
    monkeypatch.setattr(auth, "_login_or_signup", lambda _client, is_claimed, email, password: login_calls.append((is_claimed, email, password)))
    monkeypatch.setattr(auth, "_personal_org", lambda _client, _email, _org: {"id": "org-1", "name": "Acme"})
    monkeypatch.setattr(auth, "_organization_access_key", lambda _client, _org_id: "control-token")
    monkeypatch.setattr(auth, "_default_workspace", lambda _client, _org_id, _bearer: {"id": "workspace-1", "slug": "default", "name": "Default"})
    monkeypatch.setattr(auth, "upsert_url_profile", lambda name, values: saved.update(name=name, values=values))
    monkeypatch.setattr(auth, "_install_data_plane_key", lambda _client: None)
    monkeypatch.setattr(auth, "_inference_key", lambda _client, _org_id, _workspace, _bearer: {"token": "inference-token"})
    monkeypatch.setattr(auth, "seed_provider_credentials", lambda _client, _overrides: [ProviderKey("anthropic", "already configured")])
    monkeypatch.setattr(auth, "configured_model", lambda _client: model)

    def verify(gateway_url: str, token: str, selected_model: str) -> str:
        verified.append((gateway_url, token, selected_model))
        return gateway_error

    monkeypatch.setattr(auth, "verify_gateway", verify)
    result = runner.invoke(
        app,
        [
            "quickstart",
            "--email",
            "owner@example.com",
            "--password",
            "password123",
            "--gateway-url",
            "https://gateway.example.com/",
        ],
    )
    return result, login_calls, saved, verified


def test_quickstart_resumes_and_only_reports_ready_after_gateway_inference(monkeypatch, tmp_path):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))

    result, login_calls, saved, verified = _quickstart(monkeypatch, claimed=True, model="anthropic/claude-test")

    assert result.exit_code == 0, result.output
    assert login_calls == [(True, "owner@example.com", "password123")]
    assert saved["values"]["gateway_url"] == "https://gateway.example.com"
    assert verified == [("https://gateway.example.com/", "inference-token", "anthropic/claude-test")]
    assert "inference-token" in result.stdout
    assert "Ready." in result.stdout
    assert "Verified anthropic/claude-test" in result.stdout
    assert "x-airllm-dialect: canonical" in result.stdout
    assert "openai/gpt-5-nano" not in result.stdout


def test_quickstart_shows_the_new_key_but_not_ready_when_no_model_is_configured(monkeypatch, tmp_path):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))

    result, _login_calls, _saved, verified = _quickstart(monkeypatch, claimed=False, model=None)

    assert result.exit_code == 1
    assert "inference-token" in result.stdout
    assert "Setup is incomplete" in result.stdout
    assert "Ready." not in result.stdout
    assert verified == []


def test_quickstart_does_not_report_ready_when_the_gateway_request_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("GW_CLI_CONFIG", str(tmp_path / "config.toml"))

    result, _login_calls, _saved, verified = _quickstart(
        monkeypatch,
        claimed=True,
        model="anthropic/claude-test",
        gateway_error="provider rejected key",
    )

    assert result.exit_code == 1
    assert "inference-token" in result.stdout
    assert "provider rejected key" in result.stdout
    assert "Ready." not in result.stdout
    assert verified == [("https://gateway.example.com/", "inference-token", "anthropic/claude-test")]
