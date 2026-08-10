from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from uuid import UUID  # noqa: TC003 NamedTuple resolves its annotations at runtime

import pytest
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_org, make_workspace, run_in_db, setup_control_plane
from sqlalchemy.exc import IntegrityError

from contract import EnvStoreConfig, SecretNotFoundError, SecretPurpose, SecretRef, uuid7
from control_plane.models import Provider, ProviderCredential, set_actor

KEY = "sk-provider-abcd1234"
CSRF = {"X-Requested-With": "fetch"}


def _catalog(client, root):
    client.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
    client.post("/v1/taxonomy/models", json=MODEL, headers=root)


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


def test_a_credential_keeps_its_value_out_of_the_api(tmp_path):
    """The response describes the credential and never returns what was sent."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        response = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=org)
        assert response.status_code == 200, response.text
        credential = response.json()["data"]
        assert KEY not in response.text
        assert credential["fingerprint"] == "1234"
        assert credential["scope"] == "org"
        assert credential["version"] == 1
        assert _stored(cp, credential) == KEY


def test_a_workspace_brings_its_own_key(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        make_workspace(c, org, name="Staging")
        body = {"provider": "openai", "value": KEY, "workspace": "staging"}
        credential = c.post("/v1/org/provider-credentials", json=body, headers=org).json()["data"]
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
        c.post("/v1/org/provider-credentials", json={"provider": "openai", "name": "backup", "value": "sk-b", "priority": 200}, headers=org)
        c.post("/v1/org/provider-credentials", json={"provider": "openai", "name": "primary", "value": "sk-a", "priority": 10}, headers=org)
        listed = c.get("/v1/org/provider-credentials", headers=org).json()["data"]
        assert [credential["name"] for credential in listed] == ["primary", "backup"]


def test_a_name_is_taken_once_per_provider_and_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        body = {"provider": "openai", "value": KEY}
        assert c.post("/v1/org/provider-credentials", json=body, headers=org).status_code == 200
        assert c.post("/v1/org/provider-credentials", json=body, headers=org).status_code == 409


def test_a_rotation_replaces_the_value_and_bumps_the_version(tmp_path):
    """One integer of bundle diff is what makes a data plane refetch within a poll."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        created = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        rotated = c.put(f"/v1/org/provider-credentials/{created['id']}/value", json={"value": "sk-rotated-9999"}, headers=org)
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
        created = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        assert c.delete(f"/v1/org/provider-credentials/{created['id']}", headers=org).status_code == 200
        assert c.get(f"/v1/org/provider-credentials/{created['id']}", headers=org).status_code == 404
        with pytest.raises(SecretNotFoundError):
            _stored(cp, created)


def test_another_org_cannot_reach_the_credential(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        mine = cp.headers(make_org(c, root, name="mine"))
        theirs = cp.headers(make_org(c, root, name="theirs"))
        created = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=mine).json()["data"]
        assert c.get(f"/v1/org/provider-credentials/{created['id']}", headers=theirs).status_code == 404
        assert c.delete(f"/v1/org/provider-credentials/{created['id']}", headers=theirs).status_code == 404


def test_the_bundle_names_the_credential_and_carries_no_secret(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=org)
        c.post("/v1/org/bundles/compile", headers=org)
        payload = c.get("/v1/bundle/latest", headers=root).text
        assert KEY not in payload
        entry = c.get("/v1/bundle/latest", headers=root).json()["data"]["payload"]["catalog"]["credentials"][0]
        assert entry["ref"]["service"] == "openai"
        assert entry["ref"]["purpose"] == "provider"
        assert entry["version"] == 1


def test_a_disabled_credential_drops_out_of_the_bundle(tmp_path):
    """Same shape as key revocation: absence from the next bundle is what disabling means."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        created = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        c.patch(f"/v1/org/provider-credentials/{created['id']}", json={"enabled": False}, headers=org)
        c.post("/v1/org/bundles/compile", headers=org)
        payload = c.get("/v1/bundle/latest", headers=root).json()["data"]["payload"]
        assert payload["catalog"]["credentials"] == []


def test_a_rejected_body_does_not_echo_the_key(tmp_path):
    """FastAPI's default handler returns the offending input, which would put a live provider key in
    the response and in every access log between here and the caller."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        response = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": [KEY]}, headers=org)
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
        response = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=org)
        assert response.status_code == 501
        assert KEY not in response.text


def test_the_audit_trail_holds_no_value(tmp_path):
    """The audit trigger copies before and after of every column, so this is the test that the value
    never became one."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org = cp.headers(make_org(c, root))
        created = c.post("/v1/org/provider-credentials", json={"provider": "openai", "value": KEY}, headers=org).json()["data"]
        c.put(f"/v1/org/provider-credentials/{created['id']}/value", json={"value": "sk-rotated-9999"}, headers=org)
        c.delete(f"/v1/org/provider-credentials/{created['id']}", headers=org)
        trail = c.get("/v1/org/activity", headers=org)
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
        "cost_usd": 0.0,
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
    body = {"provider": "openai", "value": KEY, "workspace": str(workspace_id)}
    credential = c.post("/v1/org/provider-credentials", json=body, headers=org).json()["data"]
    return Metered(root=root, org=org, org_id=org_id, workspace_id=workspace_id, credential=credential)


def _status_of(c, m: Metered) -> str:
    return c.get(f"/v1/org/provider-credentials/{m.credential['id']}", headers=m.org).json()["data"]["status"]


def test_a_rejected_key_shows_up_as_invalid(tmp_path):
    """The data plane never talks to the control plane about credentials; the usage events it already
    sends are what carry a key's health back."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        assert m.credential["status"] == "unknown"
        event = _usage_event(m, "credential_rejected", datetime.now(tz=UTC))
        assert c.post("/v1/events", json=[event], headers=m.root).status_code == 200
        assert _status_of(c, m) == "invalid"


def test_a_working_key_shows_up_as_live(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        event = _usage_event(m, "ok", datetime.now(tz=UTC))
        c.post("/v1/events", json=[event], headers=m.root)
        assert _status_of(c, m) == "live"


def test_a_replayed_event_cannot_undo_a_newer_one(tmp_path):
    """Delivery is at-least-once, so events replay after an outage and arrive out of order. An older
    observation must never flip a working key back to invalid."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        now = datetime.now(tz=UTC)
        c.post("/v1/events", json=[_usage_event(m, "ok", now)], headers=m.root)
        stale = _usage_event(m, "credential_rejected", now - timedelta(hours=1))
        c.post("/v1/events", json=[stale], headers=m.root)
        assert _status_of(c, m) == "live"


def test_a_provider_outage_says_nothing_about_the_key(tmp_path):
    """upstream_error and timeout are facts about the provider, so they leave the status alone."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        c.post("/v1/events", json=[_usage_event(m, "ok", datetime.now(tz=UTC))], headers=m.root)
        outage = _usage_event(m, "upstream_error", datetime.now(tz=UTC) + timedelta(minutes=1))
        c.post("/v1/events", json=[outage], headers=m.root)
        assert _status_of(c, m) == "live"


def test_events_for_a_deleted_credential_are_not_an_error(tmp_path):
    """A credential can be deleted while its events are still in flight."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        c.delete(f"/v1/org/provider-credentials/{m.credential['id']}", headers=m.org)
        event = _usage_event(m, "ok", datetime.now(tz=UTC))
        assert c.post("/v1/events", json=[event], headers=m.root).status_code == 200


def test_deleting_a_workspace_takes_its_credentials(tmp_path):
    """The credential has a foreign key into the workspace, so leaving it behind does not orphan a
    row, it makes the workspace undeletable."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        deleted = c.delete(f"/v1/org/workspaces/{m.workspace_id}", headers=m.org)
        assert deleted.status_code == 200, deleted.text
        assert c.get(f"/v1/org/provider-credentials/{m.credential['id']}", headers=m.org).status_code == 404
        with pytest.raises(SecretNotFoundError):
            _stored(cp, m.credential)


def test_deleting_an_org_takes_its_credentials(tmp_path):
    """Both scopes: the workspace's credentials go with the workspace, and the org's own go with the org."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        m = _with_credential(cp, c)
        org_scoped = c.post("/v1/org/provider-credentials", json={"provider": "openai", "name": "shared", "value": KEY}, headers=m.org)
        assert org_scoped.status_code == 200, org_scoped.text
        shared = org_scoped.json()["data"]
        deleted = c.delete(f"/v1/orgs/{m.org_id}", headers=m.root)
        assert deleted.status_code == 200, deleted.text
        for credential in (m.credential, shared):
            with pytest.raises(SecretNotFoundError):
                _stored(cp, credential)


def test_a_workspace_credential_needs_workspace_membership(tmp_path):
    """Key operations require membership in the workspace, not just in the org, the way every
    inference key route already does.

    Whoever supplies a provider key owns the account the workspace's traffic is billed to, and that
    account's dashboard shows every request made with it, so attaching one is at least as privileged
    as minting an inference key.
    """
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        org_id = make_org(c, root)
        org = cp.headers(org_id)
        workspace = c.post("/v1/org/workspaces", json={"name": "Theirs"}, headers=org).json()["data"]
        outsider = c.post("/v1/auth/signup", json={"email": "out@example.com", "password": "hunter2hunter2", "name": "Out"}, headers=CSRF)
        assert outsider.status_code == 200, outsider.text
        user_id = outsider.json()["data"]["user_id"]
        c.put(f"/v1/org/users/{user_id}", headers=org)
        theirs = cp.headers_for(org_id, user_id)

        body = {"provider": "openai", "value": KEY, "workspace": workspace["slug"]}
        assert c.post("/v1/org/provider-credentials", json=body, headers=theirs).status_code == 403
        assert c.get("/v1/org/provider-credentials", params={"workspace": workspace["slug"]}, headers=theirs).status_code == 403


def test_a_platform_credential_reaches_every_org(tmp_path):
    """The platform tier is the fallback every org shares, so it belongs in every org's bundle.

    org_id == org_id never matches a null, so a platform credential compiled into nothing and the
    tier the data plane falls back to was empty for every deployment that had one.
    """
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        root = cp.headers()
        _catalog(c, root)
        provider_id = c.get("/v1/taxonomy", headers=root).json()["data"]["providers"][0]["id"]

        async def declare():
            await set_actor("root")
            await ProviderCredential(provider_id=provider_id, provider_name="openai", name="platform").save()

        run_in_db(tmp_path, declare)

        org = cp.headers(make_org(c, root))
        c.post("/v1/org/bundles/compile", headers=org)
        entries = c.get("/v1/bundle/latest", headers=root).json()["data"]["payload"]["catalog"]["credentials"]
        assert [e["ref"]["name"] for e in entries] == ["platform"]
        assert entries[0]["ref"]["org_id"] is None
