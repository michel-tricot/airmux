from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, captured_sql, inference_key_body, make_org, make_workspace, setup_control_plane, wait_for_publication
from sqlalchemy.exc import DBAPIError

from contract import INFERENCE_TOKEN_PREFIX, BundleManifest, BundleV1, token_hash
from control_plane import compiler
from control_plane.compiler import publish_next
from control_plane.db import standalone_transaction
from control_plane.models import Bundle, GlobalRuntimeConfiguration, InferenceKey, PlaygroundSession, RuntimeConfiguration, User, set_actor


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
        wait_for_publication(c, o1, org)
        latest = c.get("/api/v1/bundle/latest", params={"org_id": str(o1)}, headers=root)
        assert latest.status_code == 200
        bundle = BundleV1.model_validate(latest.json()["data"])
        bundles = c.get(f"/api/v1/organizations/{o1}/bundles", headers=org).json()["data"]
        assert [entry["version"] for entry in bundles] == [1]
        assert str(bundle.bundle_id) == bundles[-1]["id"]
        assert [k.key_id for k in bundle.keys] == [key["id"]]
        assert [k.token_hash for k in bundle.keys] == [token_hash(key["token"])]
        assert [k.workspace_id for k in bundle.keys] == [ws]
        (model,) = bundle.catalog.models
        assert model.upstream_model == "gpt-real"
        assert model.input_price_per_mtok == Decimal(1)
        assert model.output_price_per_mtok == Decimal(2)
        assert model.cache_read_price_per_mtok == Decimal("0.1")
        assert model.cache_write_price_per_mtok == Decimal("1.25")
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
        wait_for_publication(c, org_id, org)
        bundle = BundleV1.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"])
        assert bundle.keys == []
        bundles = c.get(f"/api/v1/organizations/{org_id}/bundles", headers=org).json()["data"]
        assert [entry["version"] for entry in bundles] == [1]


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
        wait_for_publication(c, org_id, org)
        created = BundleV1.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"])
        assert [entry.key_id for entry in created.keys] == [key["id"]]

        assert c.delete(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys/{key['id']}", headers=org).status_code == 200
        wait_for_publication(c, org_id, org)
        revoked = BundleV1.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"])
        assert revoked.bundle_id != created.bundle_id
        assert revoked.keys == []


def test_bundle_latest_filters_by_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        first = cp.headers(o1)
        second = cp.headers(o2)
        c.post(f"/api/v1/organizations/{o1}/bundles/republish", headers=first)
        c.post(f"/api/v1/organizations/{o2}/bundles/republish", headers=second)
        wait_for_publication(c, o1, first)
        wait_for_publication(c, o2, second)
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
        first = cp.headers(o1)
        second = cp.headers(o2)
        c.post(f"/api/v1/organizations/{o1}/bundles/republish", headers=first)
        c.post(f"/api/v1/organizations/{o2}/bundles/republish", headers=second)
        wait_for_publication(c, o1, first)
        wait_for_publication(c, o2, second)

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


def test_republish_queues_a_revision_and_returns_accepted(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        headers = cp.headers(org_id)
        response = client.post(f"/api/v1/organizations/{org_id}/bundles/republish", headers=headers)
        assert response.status_code == 202, response.text
        queued = response.json()["data"]
        assert queued["queued_revision"] == queued["publication"]["desired_revision"]
        assert queued["publication"]["status"] == "pending"
        published = wait_for_publication(client, org_id, headers, queued["queued_revision"])
        assert published["latest_bundle"]["version"] == 1


def test_management_mutation_records_revision_without_compiling_in_request(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        headers = cp.headers(org_id)
        workspace_id = make_workspace(client, headers)
        with captured_sql(cp.app) as statements:
            response = client.post(
                f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys",
                json=inference_key_body(client, headers, "queued"),
                headers=headers,
            )
        assert response.status_code == 200, response.text
        request_sql = "\n".join(statements)
        assert "INSERT INTO bundle" not in request_sql
        status = client.get(f"/api/v1/organizations/{org_id}/bundles/status", headers=headers).json()["data"]
        assert status["desired_revision"] > status["published_revision"]


def test_global_change_records_one_watermark_without_updating_each_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_ids = [make_org(client, root, f"o{number}") for number in range(3)]
        with captured_sql(cp.app) as statements:
            response = client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        assert response.status_code == 200, response.text
        updates = [statement for statement in statements if statement.startswith("INSERT INTO global_runtime_configuration")]
        assert len(updates) == 1
        assert all("runtime_configuration" not in statement for statement in statements if statement.startswith("UPDATE"))
        summary = client.get("/api/v1/instance/bundles/status", headers=root).json()["data"]
        assert summary["pending_organization_count"] == len(org_ids)
        for org_id in org_ids:
            wait_for_publication(client, org_id, cp.headers(org_id), summary["global_desired_revision"])
        current = client.get("/api/v1/instance/bundles/status", headers=root).json()["data"]
        assert current["pending_organization_count"] == 0


def test_new_organization_inherits_the_current_global_revision(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        assert client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        global_revision = client.get("/api/v1/instance/bundles/status", headers=root).json()["data"]["global_desired_revision"]
        org_id = make_org(client, root, "created-after-global-change")
        status = wait_for_publication(client, org_id, cp.headers(org_id), global_revision)
        assert status["desired_revision"] == global_revision
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", params={"org_id": str(org_id)}, headers=root).json()["data"])
        assert [provider.provider_id for provider in bundle.catalog.providers] == [PROVIDER["provider_id"]]


def test_startup_resumes_a_durable_pending_revision(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "restart")

    async def queue():
        async with standalone_transaction(cp.db_url):
            return await RuntimeConfiguration.request_republication(org_id)

    revision = asyncio.run(queue())
    assert asyncio.run(_bundles(cp.db_url, org_id)) == []
    with TestClient(cp.app) as restarted:
        status = wait_for_publication(restarted, org_id, cp.headers(org_id), revision)
    assert status["published_revision"] == revision


def test_compiler_failure_preserves_management_change_and_exposes_safe_status(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    compile_bundle = compiler.compile_bundle

    async def fail_compile(*_args, **_kwargs):
        message = "secret-value-must-not-leak"
        raise RuntimeError(message)

    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "o1")
        headers = cp.headers(org_id)
        workspace_id = make_workspace(client, headers)
        initial_request = client.post(f"/api/v1/organizations/{org_id}/bundles/republish", headers=headers).json()["data"]
        initial = wait_for_publication(client, org_id, headers, initial_request["queued_revision"])
        monkeypatch.setattr(compiler, "compile_bundle", fail_compile)
        key_response = client.post(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys",
            json=inference_key_body(client, headers, "survives-compilation-failure"),
            headers=headers,
        )
        assert key_response.status_code == 200, key_response.text
        key = key_response.json()["data"]
        deadline = datetime.now(tz=UTC).timestamp() + 5
        while True:
            response = client.get(f"/api/v1/organizations/{org_id}/bundles/status", headers=headers)
            assert response.status_code == 200, response.text
            status = response.json()["data"]
            if status["status"] == "failed":
                break
            assert datetime.now(tz=UTC).timestamp() < deadline
            time.sleep(0.1)
        assert status["desired_revision"] > initial["published_revision"]
        assert status["published_revision"] == initial["published_revision"]
        assert status["latest_bundle"] == initial["latest_bundle"]
        assert status["failure"] == {"category": "compilation_failed", "message": "Configuration could not be published"}
        assert "secret-value" not in str(status)
        keys = client.get(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys", headers=headers).json()["data"]
        assert [stored["id"] for stored in keys] == [key["id"]]
        assert [bundle["version"] for bundle in client.get(f"/api/v1/organizations/{org_id}/bundles", headers=headers).json()["data"]] == [1]
        monkeypatch.setattr(compiler, "compile_bundle", compile_bundle)
        retry = client.post(f"/api/v1/organizations/{org_id}/bundles/republish", headers=headers).json()["data"]
        recovered = wait_for_publication(client, org_id, headers, retry["queued_revision"])
        assert recovered["failure"] is None
        assert recovered["published_revision"] == retry["queued_revision"]


def test_failed_publication_backoff_starts_at_one_second_and_caps_at_sixty(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "backoff")

    async def retry_delays():
        async with standalone_transaction(cp.db_url):
            revision = await RuntimeConfiguration.request_republication(org_id)
        now = datetime.now(tz=UTC)
        delays = []
        for attempt in range(8):
            async with standalone_transaction(cp.db_url):
                await RuntimeConfiguration.record_failure(org_id, revision, now + timedelta(milliseconds=attempt))
                configuration = await RuntimeConfiguration.get(org_id)
                assert configuration is not None
                assert configuration.next_attempt_at is not None
                delays.append(round((configuration.next_attempt_at - now - timedelta(milliseconds=attempt)).total_seconds()))
        return delays

    assert asyncio.run(retry_delays()) == [1, 2, 4, 8, 16, 32, 60, 60]


def test_publish_next_is_idempotent_for_one_revision(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "o1")
        headers = cp.headers(org_id)
        queued = client.post(f"/api/v1/organizations/{org_id}/bundles/republish", headers=headers).json()["data"]
        wait_for_publication(client, org_id, headers, queued["queued_revision"])

    async def no_more_work():
        async with standalone_transaction(cp.db_url, isolation_level="REPEATABLE READ"):
            return await publish_next(datetime.now(tz=UTC))

    assert asyncio.run(no_more_work()) is None
    assert len(asyncio.run(_bundles(cp.db_url, org_id))) == 1


def test_global_revision_change_aborts_an_older_publication_snapshot(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app):
        pass

    async def race():
        async with standalone_transaction(cp.db_url, isolation_level="REPEATABLE READ"):
            revision = await GlobalRuntimeConfiguration.desired()
            async with standalone_transaction(cp.db_url):
                await GlobalRuntimeConfiguration.advance(revision + 1)
            await GlobalRuntimeConfiguration.lock_for_publication()

    with pytest.raises(DBAPIError) as caught:
        asyncio.run(race())
    assert getattr(caught.value.orig, "sqlstate", None) == "40001"


def test_desired_watermark_cannot_regress_when_revisions_commit_out_of_order(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app):
        pass

    async def commit_out_of_order():
        async with standalone_transaction(cp.db_url):
            await GlobalRuntimeConfiguration.advance(100)
        async with standalone_transaction(cp.db_url):
            await GlobalRuntimeConfiguration.advance(99)
        async with standalone_transaction(cp.db_url):
            return await GlobalRuntimeConfiguration.desired()

    assert asyncio.run(commit_out_of_order()) == 100


def test_competing_publishers_create_one_bundle_for_a_revision(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "o1")

    original_compile = compiler.compile_bundle

    async def race():
        async with standalone_transaction(cp.db_url):
            revision = await RuntimeConfiguration.request_republication(org_id)
        entered = asyncio.Event()
        release = asyncio.Event()

        async def paused_compile(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original_compile(*args, **kwargs)

        monkeypatch.setattr(compiler, "compile_bundle", paused_compile)

        async def publish():
            async with standalone_transaction(cp.db_url, isolation_level="REPEATABLE READ"):
                return await publish_next(datetime.now(tz=UTC))

        first = asyncio.create_task(publish())
        await entered.wait()
        second = await publish()
        release.set()
        return revision, await first, second

    revision, first, second = asyncio.run(race())
    assert first is not None
    assert first.configuration_revision == revision
    assert second is None
    assert [bundle.configuration_revision for bundle in asyncio.run(_bundles(cp.db_url, org_id))] == [revision]


def test_cancelling_publication_rolls_back_and_leaves_revision_pending(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "o1")

    async def cancel():
        async with standalone_transaction(cp.db_url):
            revision = await RuntimeConfiguration.request_republication(org_id)
        entered = asyncio.Event()

        async def paused_compile(*_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(compiler, "compile_bundle", paused_compile)

        async def publish():
            async with standalone_transaction(cp.db_url, isolation_level="REPEATABLE READ"):
                await publish_next(datetime.now(tz=UTC))

        publication = asyncio.create_task(publish())
        await entered.wait()
        publication.cancel()
        with pytest.raises(asyncio.CancelledError):
            await publication
        async with standalone_transaction(cp.db_url):
            status = await RuntimeConfiguration.status(org_id)
        return revision, status

    revision, status = asyncio.run(cancel())
    assert asyncio.run(_bundles(cp.db_url, org_id)) == []
    assert status.desired_revision == revision
    assert status.published_revision < revision
    assert status.status == "pending"


async def _bundles(database_url: str, org_id: UUID) -> list[Bundle]:
    async with standalone_transaction(database_url):
        return await Bundle.find(Bundle.org_id == org_id)


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
        wait_for_publication(client, org_id, headers)
        before = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=root, params={"org_id": str(org_id)}).json()["data"])

        async def change_identity():
            async with standalone_transaction(cp.db_url):
                await set_actor(before.keys[0].user_id)
                user = await User.new_service_account("Replacement").save()
                credential = await (InferenceKey if credential_kind == "inference_key" else PlaygroundSession).find_by_id(UUID(credential_id))
                assert credential is not None
                credential.user_id = user.id
                await credential.save()
                return user.id

        user_id = asyncio.run(change_identity())
        wait_for_publication(client, org_id, headers)
        after = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=root, params={"org_id": str(org_id)}).json()["data"])
        assert after.bundle_id != before.bundle_id
        assert after.keys[0].key_id == credential_id
        assert after.keys[0].user_id == user_id
