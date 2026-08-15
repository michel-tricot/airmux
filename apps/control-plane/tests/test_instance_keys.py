"""Instance keys: the credential for the endpoints that stand above any single org.

The pair of tests that matter most are the ones proving the two key types cannot stand in for each
other, since that separation is the whole reason management keys can carry a mandatory org.
"""

from __future__ import annotations

from helpers import make_user, run_in_db, seed_admin, seed_member, setup_control_plane, setup_db
from starlette.testclient import TestClient

from contract import token_hash
from control_plane.authz import ALL_SCOPES
from control_plane.keys import INSTANCE_KEY_PREFIX, MANAGEMENT_KEY_PREFIX, mint_instance_key, mint_management_key, verify_bearer
from control_plane.models import InstanceKey, Org


def test_minted_instance_key_has_its_own_prefix_and_stored_hash(tmp_path):
    setup_db(tmp_path)

    async def mint():
        admin = await seed_admin()
        key_id, token = await mint_instance_key(admin.id, label="t")
        return token, await InstanceKey.find_by_id(key_id)

    token, key = run_in_db(tmp_path, mint)
    assert token.startswith(INSTANCE_KEY_PREFIX)
    assert not token.startswith(MANAGEMENT_KEY_PREFIX)
    assert key.token_hash == token_hash(token)
    assert token not in key.model_dump_json()


def test_verify_builds_instance_scoped_claims_with_no_org(tmp_path):
    setup_db(tmp_path)

    async def flow():
        admin = await seed_admin()
        key_id, token = await mint_instance_key(admin.id, label="t")
        return admin.id, key_id, await verify_bearer(token)

    user_id, key_id, claims = run_in_db(tmp_path, flow)
    assert claims is not None
    assert claims.token_id == key_id
    assert claims.org_id is None
    assert claims.user_id == user_id
    assert claims.scopes == ALL_SCOPES


def test_verify_builds_scopes_from_the_row(tmp_path):
    setup_db(tmp_path)

    async def flow():
        admin = await seed_admin()
        _, restricted = await mint_instance_key(admin.id, label="t", scopes=["sync"])
        _, unrestricted = await mint_instance_key(admin.id, label="t")
        return await verify_bearer(restricted), await verify_bearer(unrestricted)

    restricted_claims, unrestricted_claims = run_in_db(tmp_path, flow)
    assert restricted_claims is not None
    assert restricted_claims.scopes == frozenset({"sync"})
    assert unrestricted_claims is not None
    assert unrestricted_claims.scopes == ALL_SCOPES


def test_revoked_instance_key_is_rejected(tmp_path):
    setup_db(tmp_path)

    async def flow():
        admin = await seed_admin()
        key_id, token = await mint_instance_key(admin.id, label="t")
        before = await verify_bearer(token)
        key = await InstanceKey.find_by_id(key_id)
        assert key is not None
        key.revoked = True
        await key.save()
        return before, await verify_bearer(token)

    before, after = run_in_db(tmp_path, flow)
    assert before is not None
    assert after is None


def test_losing_the_admin_bit_kills_the_instance_key(tmp_path):
    """The bit is rechecked on every request, the way membership is for a management key."""
    setup_db(tmp_path)

    async def flow():
        admin = await seed_admin()
        _, token = await mint_instance_key(admin.id, label="t")
        before = await verify_bearer(token)
        admin.instance_admin = False
        await admin.save()
        return before, await verify_bearer(token)

    before, after = run_in_db(tmp_path, flow)
    assert before is not None
    assert after is None


def test_a_management_key_never_resolves_to_instance_scope(tmp_path):
    """An org key names its org, so no management key can reach an instance endpoint by omission."""
    setup_db(tmp_path)

    async def flow():
        member, org_id = await seed_member()
        _, token = await mint_management_key(org_id, member.id, label="t")
        return org_id, await verify_bearer(token)

    org_id, claims = run_in_db(tmp_path, flow)
    assert claims is not None
    assert claims.org_id == org_id


def test_a_token_is_only_checked_against_the_table_that_minted_it(tmp_path):
    """The prefix picks the table: an instance key's secret reused under the management prefix is unknown, and vice versa."""
    setup_db(tmp_path)

    async def flow():
        admin = await seed_admin()
        _, instance_token = await mint_instance_key(admin.id, label="t")
        _, management_token = await mint_management_key((await Org(name="o2").save()).id, admin.id, label="t")
        swapped_instance = MANAGEMENT_KEY_PREFIX + instance_token.removeprefix(INSTANCE_KEY_PREFIX)
        swapped_management = INSTANCE_KEY_PREFIX + management_token.removeprefix(MANAGEMENT_KEY_PREFIX)
        return await verify_bearer(swapped_instance), await verify_bearer(swapped_management)

    assert run_in_db(tmp_path, flow) == (None, None)


def test_instance_endpoints_reject_an_org_key_and_accept_an_instance_key(tmp_path):
    """The end-to-end separation: the same admin, two key types, one door each."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        instance_headers = cp.headers()
        org_id = client.post("/v1/orgs", json={"name": "org-a"}, headers=instance_headers).json()["data"]["id"]
        org_headers = cp.headers(org_id=org_id)

        assert client.get("/v1/instance/instance-keys", headers=instance_headers).status_code == 200
        assert client.get("/v1/instance/instance-keys", headers=org_headers).status_code == 403
        assert client.get("/v1/org/management-keys", headers=org_headers).status_code == 200


def test_minting_listing_and_revoking_through_the_api(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        headers = cp.headers()
        minted = client.post("/v1/instance/instance-keys", json={"label": "ci"}, headers=headers)
        assert minted.status_code == 200, minted.text
        key = minted.json()["data"]
        assert key["token"].startswith(INSTANCE_KEY_PREFIX)

        listed = client.get("/v1/instance/instance-keys", headers=headers).json()["data"]
        assert [k["id"] for k in listed if k["id"] == key["id"]] == [key["id"]]
        assert all("token_hash" not in k for k in listed)

        minted_headers = {"authorization": f"Bearer {key['token']}"}
        assert client.get("/v1/instance/instance-keys", headers=minted_headers).status_code == 200

        revoked = client.delete(f"/v1/instance/instance-keys/{key['id']}", headers=headers)
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["data"]["status"] == "revoked"
        assert client.get("/v1/instance/instance-keys", headers=minted_headers).status_code == 401


def test_instance_keys_are_only_minted_for_instance_admins(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        headers = cp.headers()
        plain = make_user(tmp_path, "plain@example.com", "plain")
        refused = client.post("/v1/instance/instance-keys", json={"label": "ci", "user_id": str(plain.id)}, headers=headers)
        assert refused.status_code == 403
