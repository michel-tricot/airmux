from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import ValidationError
from starlette.testclient import TestClient

from data_plane.app import create_app
from data_plane.auth import authenticate, index_keys
from data_plane.config import Config, LocalBundleConfig
from data_plane.holder import BundleHolder
from data_plane.local import load_local, reload_if_changed

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


def test_a_reload_swaps_on_change_and_survives_a_broken_edit(tmp_path):
    path = _write(tmp_path)
    config = LocalBundleConfig(kind="local", path=path, cache_dir=tmp_path)
    holder = BundleHolder()
    mtime = reload_if_changed(config, holder, 0.0)
    assert holder.snapshot is not None
    served = holder.snapshot.bundle.bundle_id

    assert reload_if_changed(config, holder, mtime) == mtime  # unchanged file, no re-admit

    path.write_text("keys: []\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        reload_if_changed(config, holder, mtime)
    assert holder.snapshot.bundle.bundle_id == served  # the last good bundle keeps serving


@respx.mock
def test_local_mode_serves_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("P1_API_KEY", "sk-upstream")
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=UPSTREAM_REPLY))
    config = Config(bundle=LocalBundleConfig(kind="local", path=_write(tmp_path), cache_dir=tmp_path))
    with TestClient(create_app(config)) as client:
        assert client.get("/readyz").status_code == 200
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-inf-local-dev"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200, response.text
    assert response.json()["content"] == [{"type": "text", "text": "hi"}]
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-upstream"
