from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_org, make_workspace, run_in_db, setup_control_plane
from sqlalchemy.exc import IntegrityError

from contract import EnvStoreConfig, SecretNotFoundError, SecretPurpose, SecretRef
from control_plane.models import Provider, ProviderCredential

KEY = "sk-provider-abcd1234"


def _catalog(client, root):
    client.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
    client.post("/v1/taxonomy/models", json=MODEL, headers=root)


def _stored(cp, credential: dict, provider_name: str = "openai") -> str:
    """Read the value back the way a data plane would: from the store, by the ref the row names."""
    ref = SecretRef(
        purpose=SecretPurpose.provider,
        service=provider_name,
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
        await ProviderCredential(org_id=None, workspace_id=workspace_id, provider_id=provider.id, name="orphan").save()

    with pytest.raises(IntegrityError, match="provider_credential_workspace_needs_org"):
        run_in_db(tmp_path, orphan)
