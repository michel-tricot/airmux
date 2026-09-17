from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, captured_sql, inference_key_body, make_org, make_workspace, setup_control_plane, wait_for_publication
from sqlalchemy import text

from contract import INFERENCE_TOKEN_PREFIX, BundleManifest, BundleV1, token_hash
from control_plane import compiler
from control_plane.compiler import publish_next
from control_plane.db import current_session, standalone_transaction
from control_plane.models import Bundle, BundleState, InferenceKey, PlaygroundSession, User, set_actor


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
        bundle = BundleV1.model_validate(wait_for_publication(c, o1, org))
        bundles = asyncio.run(_bundles(cp.db_url, o1))
        assert len(bundles) == 1
        assert bundle.bundle_id == bundles[-1].id
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
        bundle = BundleV1.model_validate(wait_for_publication(c, org_id, org))
        assert bundle.keys == []
        assert len(asyncio.run(_bundles(cp.db_url, org_id))) == 1


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
        created = BundleV1.model_validate(wait_for_publication(c, org_id, org))
        assert [entry.key_id for entry in created.keys] == [key["id"]]

        assert c.delete(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys/{key['id']}", headers=org).status_code == 200
        revoked = BundleV1.model_validate(wait_for_publication(c, org_id, org, created.bundle_id))
        assert revoked.bundle_id != created.bundle_id
        assert revoked.keys == []


def test_bundle_manifest_follows_the_management_key_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        first = cp.headers(o1)
        second = cp.headers(o2)
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


def test_management_mutation_marks_bundle_stale_without_compiling_in_request(tmp_path):
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
        bundle = wait_for_publication(client, org_id, headers)
        assert [entry["key_id"] for entry in bundle["keys"]] == [response.json()["data"]["id"]]


def test_global_change_advances_one_generation_without_dirtying_each_org_row(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_ids = [make_org(client, root, f"o{number}") for number in range(3)]
        current = {org_id: wait_for_publication(client, org_id, cp.headers(org_id))["bundle_id"] for org_id in org_ids}

        async def state_before():
            async with standalone_transaction(cp.db_url):
                return await BundleState.global_generation(), {state.org_id: state.desired_generation for state in await BundleState.find()}

        global_before, org_before = asyncio.run(state_before())
        with captured_sql(cp.app) as statements:
            response = client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        assert response.status_code == 200, response.text

        async def state_after():
            async with standalone_transaction(cp.db_url):
                return await BundleState.global_generation(), {state.org_id: state.desired_generation for state in await BundleState.find()}

        global_after, org_after = asyncio.run(state_after())
        assert global_after == global_before + 1
        assert org_after == org_before
        assert "INSERT INTO bundle" not in "\n".join(statements)
        for org_id in org_ids:
            wait_for_publication(client, org_id, cp.headers(org_id), current[org_id])


def test_new_organization_inherits_current_global_inputs(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        assert client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        org_id = make_org(client, root, "created-after-global-change")
        bundle = BundleV1.model_validate(wait_for_publication(client, org_id, cp.headers(org_id)))
        assert [provider.provider_id for provider in bundle.catalog.providers] == [PROVIDER["provider_id"]]


def test_startup_resumes_durable_pending_work(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "restart")
        headers = cp.headers(org_id)
        current = wait_for_publication(client, org_id, headers)

    asyncio.run(_advance_global_generation(cp.db_url))
    with TestClient(cp.app) as restarted:
        published = wait_for_publication(restarted, org_id, cp.headers(org_id), current["bundle_id"])
    assert published["bundle_id"] != current["bundle_id"]


def test_compiler_failure_preserves_management_change_and_last_valid_bundle(tmp_path, monkeypatch):
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
        initial = wait_for_publication(client, org_id, headers)
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

            async def failure_count():
                async with standalone_transaction(cp.db_url):
                    state = await BundleState.get(org_id)
                    return state.failure_count if state is not None else 0

            if asyncio.run(failure_count()) > 0:
                break
            assert datetime.now(tz=UTC).timestamp() < deadline
            time.sleep(0.1)
        current = wait_for_publication(client, org_id, headers)
        assert current["bundle_id"] == initial["bundle_id"]
        keys = client.get(f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys", headers=headers).json()["data"]
        assert [stored["id"] for stored in keys] == [key["id"]]
        assert len(asyncio.run(_bundles(cp.db_url, org_id))) == 1
        monkeypatch.setattr(compiler, "compile_bundle", compile_bundle)
        recovered = wait_for_publication(client, org_id, headers, initial["bundle_id"])
        assert [entry["key_id"] for entry in recovered["keys"]] == [key["id"]]


def test_failed_publication_backoff_starts_at_one_second_and_caps_at_sixty(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "backoff")

    async def retry_delays():
        await _advance_global_generation(cp.db_url)
        async with standalone_transaction(cp.db_url):
            _, generations = await BundleState.target(org_id)
        now = datetime.now(tz=UTC)
        delays = []
        for attempt in range(8):
            async with standalone_transaction(cp.db_url):
                await BundleState.record_failure(org_id, generations, now + timedelta(milliseconds=attempt))
                state = await BundleState.get(org_id)
                assert state is not None
                assert state.next_attempt_at is not None
                delays.append(round((state.next_attempt_at - now - timedelta(milliseconds=attempt)).total_seconds()))
        return delays

    assert asyncio.run(retry_delays()) == [1, 2, 4, 8, 16, 32, 60, 60]


def test_publish_next_is_idempotent_for_current_generations(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "o1")
        headers = cp.headers(org_id)
        wait_for_publication(client, org_id, headers)

    async def no_more_work():
        async with standalone_transaction(cp.db_url, isolation_level="REPEATABLE READ"):
            return await publish_next(datetime.now(tz=UTC))

    assert asyncio.run(no_more_work()) is None
    assert len(asyncio.run(_bundles(cp.db_url, org_id))) == 1


def test_global_change_during_publication_remains_pending(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "global-race")
        assert client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        wait_for_publication(client, org_id, cp.headers(org_id))

    async def race():
        await _advance_global_generation(cp.db_url)
        entered = asyncio.Event()
        release = asyncio.Event()
        original_compile = compiler.compile_bundle

        async def paused_compile(*args, **kwargs):
            bundle = await original_compile(*args, **kwargs)
            entered.set()
            await release.wait()
            return bundle

        monkeypatch.setattr(compiler, "compile_bundle", paused_compile)

        async def publish():
            async with standalone_transaction(cp.db_url, isolation_level="REPEATABLE READ"):
                return await publish_next(datetime.now(tz=UTC))

        first_task = asyncio.create_task(publish())
        await entered.wait()
        async with standalone_transaction(cp.db_url):
            await set_actor("global-race")
            provider = await compiler.Provider.first(compiler.Provider.name == PROVIDER["provider_id"])
            assert provider is not None
            provider.base_url = "https://new.example/v1"
            await provider.save()
        release.set()
        first = await first_task
        monkeypatch.setattr(compiler, "compile_bundle", original_compile)
        second = await publish()
        return first, second

    first, second = asyncio.run(race())
    assert first is not None
    assert second is not None
    assert second.global_generation > first.global_generation
    assert str(BundleV1.model_validate_json(second.payload).catalog.providers[0].base_url) == "https://new.example/v1"


def test_competing_publishers_create_one_bundle_for_a_revision(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "o1")

    original_compile = compiler.compile_bundle

    async def race():
        await _advance_global_generation(cp.db_url)
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
        return await first, second

    first, second = asyncio.run(race())
    assert first is not None
    assert second is None
    pairs = [(bundle.global_generation, bundle.org_generation) for bundle in asyncio.run(_bundles(cp.db_url, org_id))]
    assert pairs.count((first.global_generation, first.org_generation)) == 1


def test_cancelling_publication_rolls_back_and_leaves_generations_pending(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers(), "o1")
        wait_for_publication(client, org_id, cp.headers(org_id))

    async def cancel():
        await _advance_global_generation(cp.db_url)
        async with standalone_transaction(cp.db_url):
            state, generations = await BundleState.target(org_id)
            current_bundle_id = state.current_bundle_id
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
            state, target = await BundleState.target(org_id)
        return generations, current_bundle_id, state, target

    generations, current_bundle_id, state, target = asyncio.run(cancel())
    assert target == generations
    assert state.current_bundle_id == current_bundle_id
    assert not state.is_current(target)


def test_raw_database_changes_dirty_bundle_input_tables_by_default(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root, "raw-sql")
        headers = cp.headers(org_id)
        workspace_id = make_workspace(client, headers)
        key = client.post(
            f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/inference-keys",
            json=inference_key_body(client, headers, "raw"),
            headers=headers,
        ).json()["data"]
        assert client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).status_code == 200
        current = wait_for_publication(client, org_id, headers)

    async def mutate():
        async with standalone_transaction(cp.db_url):
            before_global = await BundleState.global_generation()
            before_state = await BundleState.get(org_id)
            assert before_state is not None
            before_org = before_state.desired_generation
            await set_actor("raw-editor")
            await current_session().execute(text("UPDATE provider SET icon = 'changed' WHERE name = :name"), {"name": PROVIDER["provider_id"]})
        async with standalone_transaction(cp.db_url):
            await set_actor("raw-editor")
            await current_session().execute(
                text("UPDATE provider SET base_url = :url WHERE name = :name"),
                {"url": "https://raw.example/v1", "name": PROVIDER["provider_id"]},
            )
            await current_session().execute(text("UPDATE inference_key SET revoked = true WHERE id = :id"), {"id": UUID(key["id"])})
        async with standalone_transaction(cp.db_url):
            state = await BundleState.get(org_id)
            assert state is not None
            return await BundleState.global_generation(), state.desired_generation, before_global, before_org

    global_generation, org_generation, before_global, before_org = asyncio.run(mutate())
    assert global_generation == before_global + 2
    assert org_generation == before_org + 1
    with TestClient(cp.app) as restarted:
        published = wait_for_publication(restarted, org_id, cp.headers(org_id), current["bundle_id"])
    assert published["keys"] == []
    assert published["catalog"]["providers"][0]["base_url"] == "https://raw.example/v1"


async def _bundles(database_url: str, org_id: UUID) -> list[Bundle]:
    async with standalone_transaction(database_url):
        return await Bundle.find(Bundle.org_id == org_id)


async def _advance_global_generation(database_url: str) -> None:
    async with standalone_transaction(database_url):
        await current_session().execute(text("UPDATE global_bundle_state SET desired_generation = desired_generation + 1 WHERE id = 1"))


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
        before = BundleV1.model_validate(wait_for_publication(client, org_id, headers))

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
        after = BundleV1.model_validate(wait_for_publication(client, org_id, headers, before.bundle_id))
        assert after.bundle_id != before.bundle_id
        assert after.keys[0].key_id == credential_id
        assert after.keys[0].user_id == user_id
