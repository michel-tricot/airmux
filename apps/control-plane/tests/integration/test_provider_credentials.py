from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_org, make_workspace, run_in_db, setup_control_plane, wait_for_publication
from pg import db_url_for
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from airmux_runtime.secrets import EnvStoreConfig, InsecureDatabaseStoreConfig, SecretNotFoundError
from contract import BundleV1, SecretPurpose, SecretRef, uuid7
from control_plane.authz import Permission
from control_plane.db import current_session
from control_plane.models import BundleState, InsecureVaultSecret, Provider, ProviderCredential, set_actor

KEY = "sk-provider-abcd1234"


CSRF = {"X-Requested-With": "fetch"}


def _catalog(client, root):
    client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
    client.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=root)


def _collection(headers: dict[str, str], workspace: UUID | str | None = None) -> str:
    org_id = headers["X-Test-Org-Id"]
    return (
        f"/api/v1/organizations/{org_id}/workspaces/{workspace}/provider-credentials"
        if workspace is not None
        else f"/api/v1/organizations/{org_id}/provider-credentials"
    )


def _credential_path(credential: dict, org_id: UUID | str | None = None) -> str:
    return f"/api/v1/organizations/{org_id or credential['org_id']}/provider-credentials/{credential['id']}"


def _latest_bundle(client: TestClient, headers: dict[str, str]) -> BundleV1:
    return BundleV1.model_validate(wait_for_publication(client, UUID(headers["X-Test-Org-Id"]), headers))


def _stored(cp, credential: dict) -> str:
    """Read the value back the way a data plane would: from the store, by the ref the row names."""
    ref = SecretRef(
        purpose=SecretPurpose.provider,
        service=credential["provider_name"],
        name=credential["name"],
        secret_id=credential["id"],
        org_id=credential["org_id"],
        workspace_id=credential["workspace_id"],
    )
    return asyncio.run(cp.app.state.secret_store.get(ref)).reveal()


def _usage_event(metered, status, occurred_at):
    """One event as the data plane would send it, attributed to the credential that paid."""
    return {
        "event_id": str(uuid7()),
        "request_id": str(uuid7()),
        "occurred_at": occurred_at.isoformat(),
        "org_id": str(metered.org_id),
        "workspace_id": str(metered.workspace_id),
        "key_id": "k1",
        "model_id": "gpt-test",
        "provider_id": "openai",
        "bundle_id": str(uuid7()),
        "input_tokens": 1,
        "output_tokens": 1,
        "max_output_tokens": 128,
        "cost_usd": "0.0",
        "latency_ms": 1,
        "status": status,
        "stream": False,
        "credential_id": metered.credential["id"],
        "credential_scope": "workspace",
    }


class Metered(NamedTuple):
    """An org holding one workspace credential, and the headers to meter and read it back with."""

    root: dict
    org: dict
    org_id: UUID
    workspace_id: UUID
    credential: dict


def _with_credential(cp, c) -> Metered:
    root = cp.headers()
    _catalog(c, root)
    org_id = make_org(c, root)
    org = cp.headers(org_id)
    workspace_id = make_workspace(c, org)
    body = {"provider": "openai", "value": KEY}
    credential = c.post(_collection(org, workspace_id), json=body, headers=org).json()["data"]
    return Metered(root=root, org=org, org_id=org_id, workspace_id=workspace_id, credential=credential)


def _status_of(c, m: Metered) -> str:
    return c.get(_credential_path(m.credential), headers=m.org).json()["data"]["status"]


def test_a_credential_keeps_its_value_out_of_the_api(tmp_path):
    """The response describes the credential and never returns what was sent."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        response = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org)
        assert response.status_code == 200, response.text
        credential = response.json()["data"]
        assert KEY not in response.text
        assert credential["fingerprint"] == "1234"
        assert credential["scope"] == "org"
        assert credential["version"] == 1
        assert _stored(cp, credential) == KEY


def test_the_insecure_database_vault_keeps_its_plaintext_out_of_the_bundle(tmp_path):
    config = InsecureDatabaseStoreConfig(url=db_url_for(tmp_path))
    cp = setup_control_plane(tmp_path, secrets=config)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        response = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org)
        assert response.status_code == 200, response.text
        credential = response.json()["data"]
        bundle = BundleV1.model_validate(wait_for_publication(c, UUID(org["X-Test-Org-Id"]), org))
        entry = bundle.catalog.credentials[0]
        rotated = c.put(f"{_credential_path(credential)}/value", json={"value": "sk-rotated-9999"}, headers=org)
        assert rotated.status_code == 200, rotated.text

        async def stored_values():
            return [secret.value for secret in await InsecureVaultSecret.find()]

        async def vault_connections():
            result = await current_session().execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND application_name = 'airmux-insecure-vault'")
            )
            return result.scalar_one()

        assert run_in_db(tmp_path, stored_values) == ["sk-rotated-9999"]
        assert run_in_db(tmp_path, vault_connections) == 1
        assert KEY not in bundle.model_dump_json()
        assert set(entry.model_dump()) == {"ref", "priority", "version"}
        assert c.delete(_credential_path(credential), headers=org).status_code == 200

    assert run_in_db(tmp_path, stored_values) == []
    assert run_in_db(tmp_path, vault_connections) == 0


def test_an_instance_credential_can_be_created_and_listed(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        response = c.post(
            "/api/v1/instance/provider-credentials",
            json={"provider": "openai", "name": "platform", "value": KEY, "priority": 10},
            headers=root,
        )

        assert response.status_code == 200, response.text
        credential = response.json()["data"]
        assert KEY not in response.text
        assert credential["scope"] == "platform"
        assert credential["org_id"] is None
        assert credential["workspace_id"] is None
        assert credential["status"] == "unknown"
        assert _stored(cp, credential) == KEY

        listed = c.get("/api/v1/instance/provider-credentials", headers=root)
        assert listed.status_code == 200, listed.text
        assert set(listed.json()) == {"data"}
        assert [(item["id"], item["status"]) for item in listed.json()["data"]] == [(credential["id"], "unknown")]


def test_instance_provider_credentials_exclude_tenant_credentials(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        c.post(_collection(org), json={"provider": "openai", "name": "tenant", "value": KEY}, headers=org)
        c.post(
            "/api/v1/instance/provider-credentials",
            json={"provider": "openai", "name": "platform", "value": KEY},
            headers=root,
        )

        listed = c.get("/api/v1/instance/provider-credentials", headers=root).json()["data"]
        assert [(credential["scope"], credential["name"]) for credential in listed] == [("platform", "platform")]


def test_a_workspace_brings_its_own_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        make_workspace(c, org, name="Staging")
        body = {"provider": "openai", "value": KEY}
        credential = c.post(_collection(org, "staging"), json=body, headers=org).json()["data"]
        assert credential["scope"] == "workspace"
        assert credential["workspace_id"] is not None
        assert _stored(cp, credential) == KEY


def test_one_provider_holds_several_keys(tmp_path):
    """The whole point of BYOK: a scope holds a pool, listed in the order the data plane tries it."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        c.post(_collection(org), json={"provider": "openai", "name": "backup", "value": "sk-b", "priority": 200}, headers=org)
        c.post(_collection(org), json={"provider": "openai", "name": "primary", "value": "sk-a", "priority": 10}, headers=org)
        listed = c.get(_collection(org), headers=org).json()["data"]
        assert [credential["name"] for credential in listed] == ["primary", "backup"]


def test_a_name_is_taken_once_per_provider_and_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        body = {"provider": "openai", "value": KEY}
        assert c.post(_collection(org), json=body, headers=org).status_code == 200
        assert c.post(_collection(org), json=body, headers=org).status_code == 409


def test_the_database_constraint_closes_the_credential_name_race(tmp_path, monkeypatch):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        body = {"provider": "openai", "name": "Primary", "value": KEY}
        assert c.post(_collection(org), json=body, headers=org).status_code == 200

        async def miss(*_args):
            return None

        monkeypatch.setattr(ProviderCredential, "named", classmethod(miss))
        raced = c.post(_collection(org), json={**body, "name": "primary"}, headers=org)

        assert raced.status_code == 409
        assert raced.json() == {"detail": "Request conflicts with existing state"}


def test_provider_credentials_reject_empty_values(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        assert c.post(_collection(org), json={"provider": "openai", "value": ""}, headers=org).status_code == 422
        assert (
            c.post(
                _collection(org),
                json={"provider": "openai", "name": "../outside", "value": KEY},
                headers=org,
            ).status_code
            == 422
        )
        assert c.post(_collection(org), json={"provider": "openai", "value": KEY, "priority": -1}, headers=org).status_code == 422
        credential = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        assert c.patch(_credential_path(credential), json={"priority": -1}, headers=org).status_code == 422


def test_a_rotation_replaces_the_value_and_bumps_the_version(tmp_path):
    """One integer of bundle diff is what makes a data plane refetch within a poll."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        created = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        rotated = c.put(f"{_credential_path(created)}/value", json={"value": "sk-rotated-9999"}, headers=org)
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["data"]["version"] == 2
        assert rotated.json()["data"]["fingerprint"] == "9999"
        assert _stored(cp, created) == "sk-rotated-9999"


def test_deleting_a_credential_takes_its_value(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        created = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        assert c.delete(_credential_path(created), headers=org).status_code == 200
        assert c.get(_credential_path(created), headers=org).status_code == 404
        with pytest.raises(SecretNotFoundError):
            _stored(cp, created)


def test_another_org_cannot_reach_the_credential(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        mine = cp.headers(make_org(c, root, name="mine"))
        their_org_id = make_org(c, root, name="theirs")
        theirs = cp.headers(their_org_id)
        created = c.post(_collection(mine), json={"provider": "openai", "value": KEY}, headers=mine).json()["data"]
        assert c.get(_credential_path(created, their_org_id), headers=theirs).status_code == 404
        assert c.delete(_credential_path(created, their_org_id), headers=theirs).status_code == 404


def test_the_bundle_names_the_credential_and_carries_no_secret(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org)
        bundle = _latest_bundle(c, org)
        assert KEY not in bundle.model_dump_json()
        entry = bundle.catalog.credentials[0]
        assert entry.ref.service == "openai"
        assert entry.ref.purpose == "provider"
        assert entry.version == 1


def test_a_disabled_credential_drops_out_of_the_bundle(tmp_path):
    """Same shape as key revocation: absence from the next bundle is what disabling means."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        created = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        c.patch(_credential_path(created), json={"enabled": False}, headers=org)
        assert _latest_bundle(c, org).catalog.credentials == []


def test_a_rejected_body_does_not_echo_the_key(tmp_path):
    """FastAPI's default handler returns the offending input, which would put a live provider key in
    the response and in every access log between here and the caller."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        response = c.post(_collection(org), json={"provider": "openai", "value": [KEY]}, headers=org)
        assert response.status_code == 422
        assert KEY not in response.text
        assert response.json()["detail"][0]["loc"] == ["body", "value"]


def test_an_env_backed_instance_refuses_credentials(tmp_path):
    """A read-only store is a deployment choice, so it reads as unimplemented rather than as a
    failure the caller could fix by retrying."""
    cp = setup_control_plane(tmp_path, secrets=EnvStoreConfig())
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        response = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org)
        assert response.status_code == 501
        assert KEY not in response.text


def test_the_audit_trail_holds_no_value(tmp_path):
    """The audit trigger copies before and after of every column, so this is the test that the value
    never became one."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        created = c.post(_collection(org), json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        c.put(f"{_credential_path(created)}/value", json={"value": "sk-rotated-9999"}, headers=org)
        c.delete(_credential_path(created), headers=org)
        trail = c.get(f"/api/v1/organizations/{org_id}/activity", headers=org)
        assert trail.status_code == 200, trail.text
        assert KEY not in trail.text
        assert "sk-rotated-9999" not in trail.text


def test_a_workspace_credential_cannot_exist_without_an_org(tmp_path):
    """The composite foreign key is MATCH SIMPLE, so a null org skips it entirely; the check
    constraint is what actually holds the scope together."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        workspace_id = make_workspace(c, cp.headers(org_id))

    async def orphan():
        provider = await Provider.first(Provider.name == "openai")
        assert provider is not None
        await ProviderCredential(org_id=None, workspace_id=workspace_id, provider_id=provider.id, provider_name=provider.name, name="orphan").save()

    with pytest.raises(IntegrityError, match="provider_credential_workspace_needs_org"):
        run_in_db(tmp_path, orphan)


def test_a_rejected_key_shows_up_as_invalid(tmp_path):
    """The data plane never talks to the control plane about credentials; the usage events it already
    sends are what carry a key's health back."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        assert m.credential["status"] == "unknown"
        wait_for_publication(c, m.org_id, m.org)
        before = run_in_db(tmp_path, lambda: BundleState.get(m.org_id))
        assert before is not None
        event = _usage_event(m, "credential_rejected", datetime.now(tz=UTC))
        assert c.post("/api/v1/events", json=[event], headers=m.root).status_code == 200
        assert _status_of(c, m) == "invalid"
        after = run_in_db(tmp_path, lambda: BundleState.get(m.org_id))
        assert after is not None
        assert after.desired_generation == before.desired_generation


def test_an_org_data_plane_cannot_change_another_orgs_credential_health(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        first = _with_credential(cp, c)
        second = _with_credential(cp, c)
        event = {
            **_usage_event(first, "credential_rejected", datetime.now(tz=UTC)),
            "credential_id": second.credential["id"],
        }
        data_plane = cp.headers(first.org_id, permissions=[Permission.usage_ingest])

        assert c.post("/api/v1/events", json=[event], headers=data_plane).status_code == 200
        assert _status_of(c, second) == "unknown"


def test_a_working_key_shows_up_as_live(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        event = _usage_event(m, "ok", datetime.now(tz=UTC))
        c.post("/api/v1/events", json=[event], headers=m.root)
        assert _status_of(c, m) == "live"


def test_a_replayed_event_cannot_undo_a_newer_one(tmp_path):
    """Delivery is at-least-once, so events replay after an outage and arrive out of order. An older
    observation must never flip a working key back to invalid."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        now = datetime.now(tz=UTC)
        c.post("/api/v1/events", json=[_usage_event(m, "ok", now)], headers=m.root)
        stale = _usage_event(m, "credential_rejected", now - timedelta(hours=1))
        c.post("/api/v1/events", json=[stale], headers=m.root)
        assert _status_of(c, m) == "live"


def test_a_provider_outage_says_nothing_about_the_key(tmp_path):
    """upstream_error and timeout are facts about the provider, so they leave the status alone."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        c.post("/api/v1/events", json=[_usage_event(m, "ok", datetime.now(tz=UTC))], headers=m.root)
        outage = _usage_event(m, "upstream_error", datetime.now(tz=UTC) + timedelta(minutes=1))
        c.post("/api/v1/events", json=[outage], headers=m.root)
        assert _status_of(c, m) == "live"


def test_events_for_a_deleted_credential_are_not_an_error(tmp_path):
    """A credential can be deleted while its events are still in flight."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        c.delete(_credential_path(m.credential), headers=m.org)
        event = _usage_event(m, "ok", datetime.now(tz=UTC))
        assert c.post("/api/v1/events", json=[event], headers=m.root).status_code == 200


def test_deleting_a_workspace_takes_its_credentials(tmp_path):
    """The credential has a foreign key into the workspace, so leaving it behind does not orphan a
    row, it makes the workspace undeletable."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        deleted = c.delete(f"/api/v1/organizations/{m.org_id}/workspaces/{m.workspace_id}", headers=m.org)
        assert deleted.status_code == 200, deleted.text
        assert c.get(_credential_path(m.credential), headers=m.org).status_code == 404
        with pytest.raises(SecretNotFoundError):
            _stored(cp, m.credential)


def test_deleting_an_org_takes_its_credentials(tmp_path):
    """Both scopes: the workspace's credentials go with the workspace, and the org's own go with the org."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        org_scoped = c.post(_collection(m.org), json={"provider": "openai", "name": "shared", "value": KEY}, headers=m.org)
        assert org_scoped.status_code == 200, org_scoped.text
        shared = org_scoped.json()["data"]
        deleted = c.delete(f"/api/v1/organizations/{m.org_id}", headers=m.root)
        assert deleted.status_code == 200, deleted.text
        for credential in (m.credential, shared):
            with pytest.raises(SecretNotFoundError):
                _stored(cp, credential)


def test_a_workspace_credential_needs_workspace_membership(tmp_path):
    """Key operations require membership in the workspace, not just in the org, the way every
    inference key route already does.

    Whoever supplies a provider key owns the account the workspace's traffic is billed to, and that
    account's dashboard shows every request made with it, so attaching one is at least as privileged
    as creating an inference key.
    """
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        workspace = c.post(f"/api/v1/organizations/{org_id}/workspaces", json={"name": "Theirs"}, headers=org).json()["data"]
        outsider = c.post("/api/v1/auth/signup", json={"email": "out@example.com", "password": "hunter2hunter2", "name": "Out"}, headers=CSRF)
        assert outsider.status_code == 200, outsider.text
        user_id = outsider.json()["data"]["user_id"]
        c.put(f"/api/v1/organizations/{org_id}/users/{user_id}", json={"role": "member"}, headers=org)
        theirs = cp.headers_for(org_id, user_id)

        body = {"provider": "openai", "value": KEY}
        assert c.post(_collection(theirs, workspace["slug"]), json=body, headers=theirs).status_code == 403
        assert c.get(_collection(theirs, workspace["slug"]), headers=theirs).status_code == 403


def test_a_platform_credential_reaches_every_org(tmp_path):
    """The platform tier is the fallback every org shares, so it belongs in every org's bundle.

    org_id == org_id never matches a null, so a platform credential compiled into nothing and the
    tier the data plane falls back to was empty for every deployment that had one.
    """
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        provider_id = c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["providers"][0]["id"]

        async def declare():
            await set_actor("root")
            await ProviderCredential(provider_id=provider_id, provider_name="openai", name="platform").save()

        run_in_db(tmp_path, declare)

        org_id = make_org(c, root)
        org = cp.headers(org_id)
        entries = _latest_bundle(c, org).catalog.credentials
        assert [entry.ref.name for entry in entries] == ["platform"]
        assert entries[0].ref.org_id is None
