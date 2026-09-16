from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, inference_key_body, make_org, make_workspace, setup_control_plane

from contract import INFERENCE_TOKEN_PREFIX, BundleManifest, BundleV1, token_hash
from control_plane.compiler import publish_changes, publish_pending
from control_plane.db import standalone_transaction
from control_plane.models import InferenceKey, PlaygroundSession, RuntimeConfiguration, User, set_actor


def test_full_flow_to_verified_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/organizations/{o1}/workspaces/{ws}/inference-keys", json=inference_key_body(c, org, "k"), headers=org).json()["data"]
        assert key["token"].startswith(INFERENCE_TOKEN_PREFIX)
        assert c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        assert c.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=root).status_code == 200
        latest = c.get("/api/v1/bundle/latest", params={"org_id": str(o1)}, headers=root)
        assert latest.status_code == 200
        bundle = BundleV1.model_validate(latest.json()["data"])
        bundles = c.get(f"/api/v1/organizations/{o1}/bundles", headers=org).json()["data"]
        assert [entry["version"] for entry in bundles] == [1, 2, 3]
        assert str(bundle.bundle_id) == bundles[-1]["id"]
        assert [k.key_id for k in bundle.keys] == [key["id"]]
        assert [k.token_hash for k in bundle.keys] == [token_hash(key["token"])]
        assert [k.workspace_id for k in bundle.keys] == [ws]
        (model,) = bundle.catalog.models
        assert model.upstream_model == "gpt-real"
        assert model.input_price_per_mtok == 1.0
        assert model.output_price_per_mtok == 2.0
        assert model.cache_read_price_per_mtok == 0.1
        assert model.cache_write_price_per_mtok == 1.25
        assert model.parameter_support == {"temperature": "unsupported"}


def test_revocation_lands_in_next_bundle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/organizations/{org_id}/workspaces/{ws}/inference-keys", json=inference_key_body(c, org, "k"), headers=org).json()[
            "data"
        ]
        assert c.delete(f"/api/v1/organizations/{org_id}/workspaces/{ws}/inference-keys/{key['id']}", headers=org).status_code == 200
        bundle = BundleV1.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"])
        assert bundle.keys == []
        bundles = c.get(f"/api/v1/organizations/{org_id}/bundles", headers=org).json()["data"]
        assert [entry["version"] for entry in bundles] == [1, 2]


def test_inference_key_changes_publish_without_manual_action(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        workspace_id = make_workspace(c, org)

        key = c.post(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys",
            json=inference_key_body(c, org, "automatic"),
            headers=org,
        ).json()["data"]
        created = BundleV1.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"])
        assert [entry.key_id for entry in created.keys] == [key["id"]]

        assert c.delete(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys/{key['id']}", headers=org).status_code == 200
        revoked = BundleV1.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"])
        assert revoked.bundle_id != created.bundle_id
        assert revoked.keys == []


def test_bundle_latest_filters_by_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        c.post(f"/api/v1/organizations/{o1}/bundles/republish", headers=cp.headers(o1))
        c.post(f"/api/v1/organizations/{o2}/bundles/republish", headers=cp.headers(o2))
        global_latest = BundleV1.model_validate(c.get("/api/v1/bundle/latest", headers=root).json()["data"])
        assert global_latest.org_id == o2
        latest = BundleV1.model_validate(c.get("/api/v1/bundle/latest", headers=cp.headers(o2)).json()["data"])
        assert latest.org_id == o2
        scoped = c.get("/api/v1/bundle/latest", headers=root, params={"org_id": str(o1)})
        bundle = BundleV1.model_validate(scoped.json()["data"])
        assert bundle.org_id == o1


def test_bundle_manifest_follows_the_management_key_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        c.post(f"/api/v1/organizations/{o1}/bundles/republish", headers=cp.headers(o1))
        c.post(f"/api/v1/organizations/{o2}/bundles/republish", headers=cp.headers(o2))

        instance = BundleManifest.model_validate(c.get("/api/v1/bundles/manifest", headers=root).json()["data"])
        org = BundleManifest.model_validate(c.get("/api/v1/bundles/manifest", headers=cp.headers(o1)).json()["data"])

        assert {bundle.org_id for bundle in instance.bundles} == {o1, o2}
        assert [bundle.org_id for bundle in org.bundles] == [o1]
        by_org = {bundle.org_id: bundle for bundle in instance.bundles}
        response = c.get(f"/api/v1/bundles/{by_org[o1].bundle_id}", headers=cp.headers(o1))
        assert response.status_code == 200
        assert "payload" not in response.json()["data"]
        assert BundleV1.model_validate(response.json()["data"]).org_id == o1
        assert c.get(f"/api/v1/bundles/{by_org[o2].bundle_id}", headers=cp.headers(o1)).status_code == 403
        workspace_id = make_workspace(c, cp.headers(o1))
        assert c.get("/api/v1/bundles/manifest", headers=cp.headers(o1, workspace_id=workspace_id)).status_code == 403


def test_concurrent_publications_allocate_distinct_versions(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        org_id = make_org(c, cp.headers(), "o1")

    async def publish() -> int:
        async with standalone_transaction(cp.db_url):
            await RuntimeConfiguration.request_republication(org_id)
            bundles = await publish_pending(datetime.now(tz=UTC))
            return bundles[0].version

    async def publish_both() -> list[int]:
        return list(await asyncio.gather(publish(), publish()))

    assert sorted(asyncio.run(publish_both())) == [1, 2]


def test_compile_endpoint_is_removed(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        org_id = make_org(c, cp.headers(), "o1")
        assert c.post(f"/api/v1/organizations/{org_id}/bundles/compile", headers=cp.headers(org_id)).status_code == 404


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/instance/taxonomy/providers", {**PROVIDER, "base_url": "not-a-url"}),
        ("/api/v1/instance/taxonomy/models", {**MODEL, "input_price_per_mtok": -1}),
        ("/api/v1/instance/taxonomy/models", {**MODEL, "context_window": 0}),
        ("/api/v1/instance/taxonomy/models", {**MODEL, "unexpected": True}),
    ],
)
def test_taxonomy_rejects_values_that_cannot_form_a_valid_bundle(tmp_path, path, body):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        if path.endswith("models"):
            assert c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        assert c.post(path, json=body, headers=root).status_code == 422


@pytest.mark.parametrize("credential_kind", ["inference_key", "playground_session"])
def test_principal_identity_changes_publish_updated_bundle(tmp_path, credential_kind):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "identity-publication")
        headers = cp.headers(org_id)
        workspace_id = make_workspace(client, headers)
        base = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}"
        if credential_kind == "inference_key":
            credential_id = client.post(f"{base}/inference-keys", headers=headers, json=inference_key_body(client, headers, "Identity")).json()[
                "data"
            ]["id"]
        else:
            credential_id = client.put(f"{base}/playground-session", headers=headers).json()["data"]["id"]
        before = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=root, params={"org_id": str(org_id)}).json()["data"])

        async def change_identity():
            async with standalone_transaction(cp.db_url):
                await set_actor(before.keys[0].user_id)
                user = await User.new_service_account("Replacement").save()
                credential = await (InferenceKey if credential_kind == "inference_key" else PlaygroundSession).find_by_id(UUID(credential_id))
                assert credential is not None
                credential.user_id = user.id
                await credential.save()
                await publish_changes(datetime.now(tz=UTC))
                return user.id

        user_id = asyncio.run(change_identity())
        after = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=root, params={"org_id": str(org_id)}).json()["data"])
        assert after.bundle_id != before.bundle_id
        assert after.keys[0].key_id == credential_id
        assert after.keys[0].user_id == user_id
