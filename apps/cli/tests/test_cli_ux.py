from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from pydantic import BaseModel
from typer.testing import CliRunner

from api_models import ModelOut, ProviderOut, TaxonomyOut
from cli import client, diagnostics, resources
from cli.client import Page
from cli.main import app
from cli.profiles import Profile, upsert_profile

runner = CliRunner()


class Item(BaseModel):
    id: int


class Event(BaseModel):
    event_id: int


class PaginatedClient:
    def __init__(self) -> None:
        self.queries: list[dict[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, path: str, params: dict[str, object]) -> httpx.Response:
        self.queries.append(params)
        cursor = params.get("cursor")
        body = {"data": [{"id": 2}], "page": {"next_cursor": None}} if cursor == "next" else {"data": [{"id": 1}], "page": {"next_cursor": "next"}}
        return httpx.Response(200, request=httpx.Request("GET", f"http://control-plane{path}"), json=body)


def test_version_is_available_without_a_command():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("airmux ")


def test_access_get_follows_cursors_only_when_all_pages_is_requested(monkeypatch):
    first_page_client = PaginatedClient()
    monkeypatch.setattr(client, "access_client", lambda _url: first_page_client)

    first_page = client.access_get("/items", "", Item, limit=1)

    assert [item.id for item in first_page] == [1]
    assert first_page_client.queries == [{"limit": 1}]

    all_pages_client = PaginatedClient()
    monkeypatch.setattr(client, "access_client", lambda _url: all_pages_client)

    all_pages = client.access_get("/items", "", Item, limit=1, all_pages=True)

    assert [item.id for item in all_pages] == [1, 2]
    assert all_pages_client.queries == [{"limit": 1}, {"limit": 1, "cursor": "next"}]


def test_access_get_accepts_an_unpaged_collection(monkeypatch):
    response = httpx.Response(200, request=httpx.Request("GET", "http://control-plane/items"), json={"data": [{"id": 1}]})
    http_client = httpx.Client(base_url="http://control-plane", transport=httpx.MockTransport(lambda _request: response))
    monkeypatch.setattr(client, "access_client", lambda _url: http_client)

    items = client.access_get("/items", "", Item)

    assert [item.id for item in items] == [1]


def test_event_tail_walks_pages_until_the_previous_newest_event(monkeypatch):
    pages = iter(
        (
            Page(items=[Event(event_id=5), Event(event_id=4)], next_cursor="older"),
            Page(items=[Event(event_id=3), Event(event_id=2)], next_cursor="oldest"),
            Page(items=[Event(event_id=1), Event(event_id=0)], next_cursor=None),
        )
    )
    queries = []

    monkeypatch.setattr(resources, "payload_page", lambda _response, _payload_type: next(pages))

    def respond(request: httpx.Request) -> httpx.Response:
        queries.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, request=request, json={"data": []})

    with httpx.Client(base_url="http://control-plane", transport=httpx.MockTransport(respond)) as events_client:
        events = resources._events_since(events_client, "/events", "1")

    assert [event.event_id for event in events] == [2, 3, 4, 5]
    assert queries == [
        ("/events", {"limit": "200"}),
        ("/events", {"limit": "200", "cursor": "older"}),
        ("/events", {"limit": "200", "cursor": "oldest"}),
    ]


def test_status_shows_the_active_context_without_its_token(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    upsert_profile(
        "acme",
        Profile(
            scope="org",
            control_plane_url="https://airmux.example.com",
            gateway_url="https://gateway.example.com",
            org_id="org-1",
            org_name="Acme",
            workspace="production",
            token="secret-token",
        ),
    )

    result = runner.invoke(app, ["status", "-f", "json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [
        {
            "profile": "acme",
            "control_plane": "https://airmux.example.com",
            "gateway": "https://gateway.example.com",
            "organization": "Acme",
            "workspace": "production",
            "authentication": "profile",
        }
    ]
    assert "secret-token" not in result.stdout


def test_doctor_renders_every_check_and_fails_when_one_is_unhealthy(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setattr(
        diagnostics,
        "diagnostic_rows",
        lambda _control_plane_url, _gateway_url: [
            {"check": "Control plane", "status": "ok", "detail": "reachable"},
            {"check": "Gateway", "status": "failed", "detail": "no bundle"},
        ],
    )

    result = runner.invoke(app, ["doctor", "-f", "json"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == [
        {"check": "Control plane", "status": "ok", "detail": "reachable"},
        {"check": "Gateway", "status": "failed", "detail": "no bundle"},
    ]


def test_doctor_accepts_environment_credentials_without_a_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "environment-token")
    client_class = httpx.Client
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"data": {}}))
    monkeypatch.setattr(diagnostics.httpx, "Client", lambda **_kwargs: client_class(transport=transport))

    rows = diagnostics.diagnostic_rows("https://control.example.com", "https://gateway.example.com")

    assert rows[0] == {"check": "CLI config", "status": "ok", "detail": "using environment credentials"}


def test_catalog_tables_lead_with_stable_names(monkeypatch):
    now = datetime.now(tz=UTC)
    provider_id = uuid4()
    monkeypatch.setattr(
        resources,
        "_taxonomy",
        lambda _url: TaxonomyOut(
            providers=[
                ProviderOut(
                    id=provider_id,
                    name="openai",
                    kind="openai",
                    base_url="https://api.openai.com",
                    icon="",
                    param_aliases={},
                    accepted_params=None,
                    params_closed=False,
                    created_at=now,
                    updated_at=now,
                )
            ],
            models=[
                ModelOut(
                    id=uuid4(),
                    name="openai/gpt-test",
                    provider_id=provider_id,
                    upstream_model="gpt-test",
                    egress_kind=None,
                    input_price_per_mtok="1",
                    output_price_per_mtok="2",
                    cache_read_price_per_mtok="0",
                    cache_write_price_per_mtok="0",
                    context_window=1000,
                    max_output_tokens=100,
                    input_modalities=["text"],
                    output_modalities=["text"],
                    capabilities=["streaming"],
                    parameter_support={},
                    created_at=now,
                    updated_at=now,
                )
            ],
        ),
    )

    providers = runner.invoke(app, ["providers", "list"])
    models = runner.invoke(app, ["models", "list"])

    assert providers.exit_code == 0, providers.output
    assert models.exit_code == 0, models.output
    assert "openai" in providers.stdout
    assert str(provider_id) not in providers.stdout
    assert "openai/gpt-test" in models.stdout
    assert "openai" in models.stdout
