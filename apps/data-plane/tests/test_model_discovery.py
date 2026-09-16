from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, cast

import pytest
import respx
from conftest import (
    MODEL,
    NOW,
    ORG,
    PLATFORM_CREDENTIAL,
    PROVIDER,
    WORKSPACE,
    make_bundle,
    make_config,
    make_credential,
    make_key,
    mock_control_plane,
)
from openai import AuthenticationError, NotFoundError, OpenAI
from pydantic import ValidationError
from starlette.testclient import TestClient

from contract import Catalog, uuid7
from contract.policies import PolicyDefinition, PolicyEntry, RuleDefinition, RuleEntry
from data_plane.app import create_app
from data_plane.bundle.holder import BundleSet
from data_plane.cache import CachedBundles, write_cached_bundles
from data_plane.discovery import ModelInfoOut

if TYPE_CHECKING:
    from data_plane.runtime import Runtime

PATHS = ("/inf/v1/models", "/inf/v1/models/gpt-test")


@respx.mock
def test_openai_sdk_lists_and_retrieves_gateway_models(api_key, dp_app):
    mock_control_plane()
    with TestClient(dp_app) as client:
        sdk = OpenAI(base_url="http://testserver/inf/v1", api_key=api_key, http_client=client)
        models = list(sdk.models.list())
        assert len(models) == 1
        model = sdk.models.retrieve(models[0].id)
        assert model == models[0]
        assert (model.id, model.object, model.owned_by, model.created) == (MODEL.model_id, "model", PROVIDER.provider_id, int(NOW.timestamp()))
        assert model.model_extra is not None
        assert model.model_extra["gateway"] == {
            "context_window": MODEL.context_window,
            "max_output_tokens": MODEL.max_output_tokens,
            "input_modalities": MODEL.input_modalities,
            "output_modalities": MODEL.output_modalities,
            "capabilities": MODEL.capabilities,
            "parameter_support": MODEL.parameter_support,
        }


@respx.mock
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("token", [None, "sk-cp-not-an-inference-key", "sk-inf-unknown"])
def test_discovery_requires_an_active_inference_key(dp_app, path, token):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.get(path, headers={"Authorization": f"Bearer {token}"} if token else {})
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert response.headers["cache-control"] == "no-store"


@respx.mock
def test_sdk_discovery_errors_are_typed(dp_app):
    mock_control_plane()
    with TestClient(dp_app) as client:
        sdk = OpenAI(base_url="http://testserver/inf/v1", api_key="sk-inf-unknown", http_client=client, max_retries=0)
        with pytest.raises(AuthenticationError):
            sdk.models.list()


@respx.mock
@pytest.mark.parametrize("path", PATHS)
def test_discovery_rejects_expired_keys(tmp_path, path):
    token, key = make_key()
    bundle = make_bundle(
        keys=[key.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})],
        catalog=Catalog(providers=[PROVIDER], models=[MODEL], credentials=[PLATFORM_CREDENTIAL]),
    )
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


@respx.mock
@pytest.mark.parametrize("path", PATHS)
def test_discovery_returns_503_without_a_bundle(tmp_path, path):
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        response = client.get(path)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "bundle_unavailable"


@respx.mock
def test_gateway_model_ids_can_contain_slashes_and_do_not_expose_upstream_details(tmp_path):
    token, key = make_key()
    model = MODEL.model_copy(update={"model_id": "p1/model/version", "upstream_model": "private-deployment"})
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[model], credentials=[PLATFORM_CREDENTIAL]))
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        sdk = OpenAI(base_url="http://testserver/inf/v1", api_key=token, http_client=client, max_retries=0)
        assert sdk.models.retrieve(model.model_id).id == model.model_id
        with pytest.raises(NotFoundError):
            sdk.models.retrieve("unknown/model")
        response = client.get("/inf/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert response.json()["object"] == "list"
    assert response.headers["cache-control"] == "no-store"
    assert "private-deployment" not in response.text
    assert str(PROVIDER.base_url) not in response.text
    assert str(PLATFORM_CREDENTIAL.ref.secret_id) not in response.text


def discovery_bundle(action, *, match=None, target=None, workspace=WORKSPACE, credentials=(PLATFORM_CREDENTIAL,)):
    token, key = make_key()
    rule = RuleEntry(
        id=uuid7(),
        workspace_id=workspace,
        name="discovery",
        definition=RuleDefinition.model_validate({"match": match or {"kind": "all_requests"}, "action": action}),
    )
    policy = PolicyEntry(
        id=uuid7(),
        workspace_id=workspace,
        name="discovery",
        priority=100,
        definition=PolicyDefinition.model_validate({"target": target or {"kind": "workspace"}, "rule_ids": [rule.id]}),
    )
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL], credentials=list(credentials)))
    return token, bundle.model_copy(update={"rules": (rule,), "policies": (policy,)})


@respx.mock
@pytest.mark.parametrize("target", [{"kind": "workspace"}, {"kind": "selected_keys", "key_ids": ["k-dev"]}])
@pytest.mark.parametrize(
    "action",
    [
        {"kind": "models", "names": ["another-model"]},
        {"kind": "providers", "names": ["another-provider"]},
        {"kind": "deny", "message": "Inference disabled"},
        {"kind": "credential_access", "scopes": ["workspace", "org"]},
        {"kind": "price_limit", "max_input_price_per_mtok": "0", "max_output_price_per_mtok": "0"},
    ],
)
def test_discovery_hides_models_blocked_by_model_policies(tmp_path, action, target):
    token, bundle = discovery_bundle(action, target=target)
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/inf/v1/models", headers=headers).json() == {"object": "list", "data": []}
        response = client.get("/inf/v1/models/gpt-test", headers=headers)
        unknown = client.get("/inf/v1/models/unknown", headers=headers)
    assert response.status_code == unknown.status_code == 404
    assert response.json() == unknown.json()
    assert response.headers["cache-control"] == "no-store"


@respx.mock
@pytest.mark.parametrize(
    "options",
    [
        {"workspace": uuid7()},
        {"target": {"kind": "selected_keys", "key_ids": ["another-key"]}},
        {"match": {"kind": "request", "models": ["another-model"]}},
        {"match": {"kind": "request", "stream": False}},
        {"match": {"kind": "request", "stream": True}},
        {"match": {"kind": "request", "capabilities": ["tools"]}},
    ],
)
def test_discovery_preserves_key_workspace_and_request_match_scoping(tmp_path, options):
    token, bundle = discovery_bundle({"kind": "deny", "message": "Restricted request"}, **options)
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        headers = {"Authorization": f"Bearer {token}"}
        assert [model["id"] for model in client.get("/inf/v1/models", headers=headers).json()["data"]] == [MODEL.model_id]
        assert client.get("/inf/v1/models/gpt-test", headers=headers).status_code == 200


@respx.mock
@pytest.mark.parametrize("credentials", [(), (make_credential(workspace=uuid7()),)])
def test_models_without_credentials_in_the_callers_scope_are_hidden(tmp_path, credentials):
    token, bundle = discovery_bundle({"kind": "models", "names": [MODEL.model_id]}, credentials=credentials)
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        response = client.get("/inf/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["data"] == []


@respx.mock
@pytest.mark.parametrize("scope", ["platform", "org", "workspace"])
def test_discovery_includes_models_with_credentials_allowed_by_policy(tmp_path, scope):
    credentials = {
        "platform": PLATFORM_CREDENTIAL,
        "org": make_credential(),
        "workspace": make_credential(workspace=WORKSPACE),
    }
    token, bundle = discovery_bundle({"kind": "credential_access", "scopes": [scope]}, credentials=(credentials[scope],))
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        response = client.get("/inf/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert [model["id"] for model in response.json()["data"]] == [MODEL.model_id]


@respx.mock
@pytest.mark.parametrize(
    "action",
    [
        {"kind": "strict_parameters"},
        {"kind": "request_limits", "max_output_tokens": 1},
        {"kind": "budget", "period": "day", "amount_usd": "1", "sharing": "per_key"},
        {"kind": "fallback", "models": ["backup"], "on": ["timeout"], "max_attempts": 2, "timeout_ms": 100},
    ],
)
def test_discovery_defers_inference_only_actions(tmp_path, action):
    token, bundle = discovery_bundle(action)
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        response = client.get("/inf/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert [model["id"] for model in response.json()["data"]] == [MODEL.model_id]


@pytest.mark.parametrize(
    "metadata",
    [
        {"input_modalities": ["unknown"]},
        {"output_modalities": ["unknown"]},
        {"capabilities": ["unknown"]},
        {"parameter_support": {"temperature": "unknown"}},
    ],
)
def test_discovery_metadata_rejects_unknown_vocabulary(metadata):
    with pytest.raises(ValidationError):
        ModelInfoOut.model_validate(
            {
                "context_window": MODEL.context_window,
                "max_output_tokens": MODEL.max_output_tokens,
                "input_modalities": MODEL.input_modalities,
                "output_modalities": MODEL.output_modalities,
                "capabilities": MODEL.capabilities,
                "parameter_support": MODEL.parameter_support,
                **metadata,
            }
        )


@respx.mock
def test_model_matching_policies_only_hide_the_selected_model(tmp_path):
    token, bundle = discovery_bundle({"kind": "deny", "message": "Model disabled"}, match={"kind": "request", "models": [MODEL.model_id]})
    other = MODEL.model_copy(update={"model_id": "another-model"})
    bundle = bundle.model_copy(update={"catalog": bundle.catalog.model_copy(update={"models": [MODEL, other]})})
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        response = client.get("/inf/v1/models", headers={"Authorization": f"Bearer {token}"})
    assert [model["id"] for model in response.json()["data"]] == [other.model_id]


@respx.mock
def test_discovery_uses_the_callers_org_and_the_current_bundle(tmp_path):
    other_org = uuid7()
    token, key = make_key("first")
    other_token, other_key = make_key("second", org=other_org, workspace=uuid7())
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL], credentials=[PLATFORM_CREDENTIAL]))
    other_model = MODEL.model_copy(update={"model_id": "other-org-model"})
    other_bundle = make_bundle(
        keys=[other_key], org=other_org, catalog=Catalog(providers=[PROVIDER], models=[other_model], credentials=[PLATFORM_CREDENTIAL])
    )
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle, other_bundle]))
    mock_control_plane()
    with TestClient(create_app(make_config(tmp_path, "devnull"))) as client:
        headers = {"Authorization": f"Bearer {token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}
        assert [model["id"] for model in client.get("/inf/v1/models", headers=headers).json()["data"]] == [MODEL.model_id]
        assert [model["id"] for model in client.get("/inf/v1/models", headers=other_headers).json()["data"]] == [other_model.model_id]
        assert client.get("/inf/v1/models/other-org-model", headers=headers).status_code == 404
        runtime = cast("Runtime", client.app_state["runtime"])
        changed = bundle.model_copy(update={"catalog": bundle.catalog.model_copy(update={"models": [MODEL, other_model]})})
        runtime.holder.swap(BundleSet.from_bundles((changed, other_bundle)), source="test")
        assert len(client.get("/inf/v1/models", headers=headers).json()["data"]) == 2
        revoked = changed.model_copy(update={"keys": []})
        runtime.holder.swap(BundleSet.from_bundles((revoked, other_bundle)), source="test")
        assert client.get("/inf/v1/models", headers=headers).status_code == 401
        assert runtime.holder.current.snapshots[ORG].bundle.bundle_id == revoked.bundle_id
