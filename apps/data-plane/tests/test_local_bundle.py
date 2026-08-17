from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import respx
from conftest import make_outbox
from pydantic import ValidationError
from starlette.testclient import TestClient

from contract import FileStoreConfig, Secret
from data_plane.app import create_app
from data_plane.auth import authenticate, index_keys
from data_plane.bundle import BundleHolder, LocalBundleConfig
from data_plane.bundle.local import LocalBundleSource, load_local
from data_plane.config import Config, SqliteOutboxConfig
from data_plane.control_plane_link import ControlPlaneLink

if TYPE_CHECKING:
    from data_plane.runtime import Runtime

NOW = datetime.now(tz=UTC)

BUNDLE_YML = """
keys:
  - sk-inf-local-dev
providers:
  - provider_id: p1
    kind: openai_compatible
    base_url: https://api.openai.com/v1
models:
  - model_id: gpt-test
    provider_id: p1
    upstream_model: gpt-real
    input_price_per_mtok: 1.0
    output_price_per_mtok: 2.0
    cache_read_price_per_mtok: 0.1
    cache_write_price_per_mtok: 1.25
    context_window: 128000
    capabilities: [streaming]
"""

UPSTREAM_REPLY = {
    "id": "chatcmpl-1",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _write(tmp_path, text=BUNDLE_YML):
    path = tmp_path / "bundle.yml"
    path.write_text(text, encoding="utf-8")
    return path


def _recorded(cache_dir, http_client):
    outbox = make_outbox(cache_dir, http_client)
    events = outbox.next_batch(10)
    outbox.close()
    return events


def test_the_compiled_bundle_authenticates_the_plaintext_key(tmp_path):
    bundle = load_local(_write(tmp_path), NOW)
    key = authenticate("sk-inf-local-dev", index_keys(bundle))
    assert key is not None
    assert authenticate("sk-inf-wrong", index_keys(bundle)) is None


def test_one_platform_credential_per_provider_with_stable_ids(tmp_path):
    """The env store resolves the credential as P1_API_KEY; a stable secret_id keeps the
    resolver cache warm across reloads."""
    path = _write(tmp_path)
    first = load_local(path, NOW)
    second = load_local(path, NOW)
    (credential,) = first.catalog.credentials
    assert credential.ref.service == "p1"
    assert credential.ref.org_id is None
    assert credential.ref.secret_id == second.catalog.credentials[0].ref.secret_id
    assert first.bundle_id == second.bundle_id


def test_the_bundle_id_follows_the_file_content(tmp_path):
    path = _write(tmp_path)
    before = load_local(path, NOW)
    path.write_text(BUNDLE_YML.replace("sk-inf-local-dev", "sk-inf-other"), encoding="utf-8")
    assert load_local(path, NOW).bundle_id != before.bundle_id


async def test_a_reload_swaps_on_change_and_survives_a_broken_edit(tmp_path):
    path = _write(tmp_path)
    config = LocalBundleConfig(kind="local", path=path)
    holder = BundleHolder()
    source = LocalBundleSource(config, holder)
    await source.once()
    assert holder.snapshot is not None
    served = holder.snapshot.bundle.bundle_id
    snapshot = holder.snapshot

    await source.once()
    assert holder.snapshot is snapshot

    path.write_text("keys: []\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        await source.once()
    assert holder.snapshot.bundle.bundle_id == served  # the last good bundle keeps serving


@respx.mock
def test_local_mode_serves_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("P1_API_KEY", "sk-upstream")
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=UPSTREAM_REPLY))
    config = Config(bundle=LocalBundleConfig(kind="local", path=_write(tmp_path)))
    with TestClient(create_app(config)) as client:
        assert client.get("/readyz").status_code == 200
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": "Bearer sk-inf-local-dev"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200, response.text
    assert response.json()["content"] == [{"type": "text", "text": "hi"}]
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-upstream"


@respx.mock
def test_local_bundle_source_does_not_disable_event_export(tmp_path, monkeypatch):
    monkeypatch.setenv("P1_API_KEY", "sk-upstream")
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=UPSTREAM_REPLY))
    exported = threading.Event()

    def accept_events(_request):
        exported.set()
        return httpx.Response(200, json={"received": 1, "ingested": 1})

    respx.post("http://cp.test/api/v1/events").mock(side_effect=accept_events)
    config = Config(
        bundle=LocalBundleConfig(kind="local", path=_write(tmp_path)),
        events=SqliteOutboxConfig(
            control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),
            cache_dir=tmp_path,
            flush_interval_s=0.01,
        ),
    )

    with TestClient(create_app(config)) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": "Bearer sk-inf-local-dev"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        assert exported.wait(1)


@respx.mock
def test_app_instances_keep_their_own_runtime(tmp_path, http_client):
    first_path = tmp_path / "first.yml"
    first_path.write_text(BUNDLE_YML.replace("sk-inf-local-dev", "sk-inf-first"), encoding="utf-8")
    second_path = tmp_path / "second.yml"
    second_path.write_text(BUNDLE_YML.replace("sk-inf-local-dev", "sk-inf-second"), encoding="utf-8")
    first_bundle = load_local(first_path, NOW)
    second_bundle = load_local(second_path, NOW)
    first_secrets = FileStoreConfig(root=tmp_path / "first-secrets")
    second_secrets = FileStoreConfig(root=tmp_path / "second-secrets")
    asyncio.run(first_secrets.build().put(first_bundle.catalog.credentials[0].ref, Secret("sk-first")))
    asyncio.run(second_secrets.build().put(second_bundle.catalog.credentials[0].ref, Secret("sk-second")))
    first_events = tmp_path / "first-events"
    second_events = tmp_path / "second-events"
    first = create_app(
        Config(
            bundle=LocalBundleConfig(kind="local", path=first_path),
            secrets=first_secrets,
            events=SqliteOutboxConfig(
                control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),
                cache_dir=first_events,
                flush_interval_s=3600,
            ),
        )
    )
    second = create_app(
        Config(
            bundle=LocalBundleConfig(kind="local", path=second_path),
            secrets=second_secrets,
            events=SqliteOutboxConfig(
                control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),
                cache_dir=second_events,
                flush_interval_s=3600,
            ),
        )
    )
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=UPSTREAM_REPLY))
    body = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}

    with TestClient(first) as first_client, TestClient(second) as second_client:
        first_http_client = cast("Runtime", first_client.app_state["runtime"]).http_client
        second_http_client = cast("Runtime", second_client.app_state["runtime"]).http_client
        assert first_http_client is not second_http_client
        assert not first_http_client.is_closed
        assert not second_http_client.is_closed
        first_response = first_client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": "Bearer sk-inf-first"},
            json=body,
        )
        second_response = second_client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": "Bearer sk-inf-second"},
            json=body,
        )

    assert first_http_client.is_closed
    assert second_http_client.is_closed
    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert [call.request.headers["authorization"] for call in route.calls] == ["Bearer sk-first", "Bearer sk-second"]
    assert [event.bundle_id for event in _recorded(first_events, http_client)] == [first_bundle.bundle_id]
    assert [event.bundle_id for event in _recorded(second_events, http_client)] == [second_bundle.bundle_id]
