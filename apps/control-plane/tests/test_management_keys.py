from __future__ import annotations

from helpers import make_org, run_in_db, seed_admin, seed_member, setup_control_plane, setup_db
from starlette.testclient import TestClient

from contract import INFERENCE_TOKEN_PREFIX, token_hash, uuid7
from control_plane.authz import ALL_SCOPES
from control_plane.keys import MANAGEMENT_KEY_PREFIX, mint_management_key, verify_management_key
from control_plane.models import ManagementKey, OrgMembership, User


def test_minted_token_has_prefix_and_stored_hash(tmp_path):
    setup_db(tmp_path)

    async def mint():
        member, org_id = await seed_member()
        token_id, token = await mint_management_key(org_id, member.id, label="t")
        return token, await ManagementKey.find_by_id(token_id)

    token, key = run_in_db(tmp_path, mint)
    assert token.startswith(MANAGEMENT_KEY_PREFIX)
    assert key.token_hash == token_hash(token)
    assert token not in key.model_dump_json()


def test_verify_accepts_a_minted_token_and_builds_claims_from_the_row(tmp_path):
    setup_db(tmp_path)

    async def flow():
        member, org_id = await seed_member()
        token_id, token = await mint_management_key(org_id, member.id, label="t")
        return member.id, org_id, token_id, await verify_management_key(token)

    user_id, org_id, token_id, claims = run_in_db(tmp_path, flow)
    assert claims is not None
    assert claims.token_id == token_id
    assert claims.org_id == org_id
    assert claims.user_id == user_id


def test_verify_builds_scopes_from_the_row(tmp_path):
    setup_db(tmp_path)

    async def mint_and_verify():
        member, org_id = await seed_member()
        _, restricted = await mint_management_key(org_id, member.id, label="t", scopes=["sync"])
        _, unrestricted = await mint_management_key(org_id, member.id, label="t")
        return await verify_management_key(restricted), await verify_management_key(unrestricted)

    restricted_claims, unrestricted_claims = run_in_db(tmp_path, mint_and_verify)
    assert restricted_claims is not None
    assert restricted_claims.scopes == frozenset({"sync"})
    assert unrestricted_claims is not None
    assert unrestricted_claims.scopes == ALL_SCOPES


def test_find_by_id_round_trips_identified_rows(tmp_path):
    setup_db(tmp_path)

    async def flow():
        admin = await seed_admin()
        return admin.id, await User.find_by_id(admin.id), await User.find_by_id(uuid7())

    admin_id, found, missing = run_in_db(tmp_path, flow)
    assert found is not None
    assert found.id == admin_id
    assert missing is None


def test_revoked_row_is_rejected(tmp_path):
    setup_db(tmp_path)

    async def flow():
        member, org_id = await seed_member()
        token_id, token = await mint_management_key(org_id, member.id, label="t")
        before = await verify_management_key(token)
        key = await ManagementKey.find_by_id(token_id)
        assert key is not None
        key.revoked = True
        await key.save()
        return before, await verify_management_key(token)

    before, after = run_in_db(tmp_path, flow)
    assert before is not None
    assert after is None


def test_unknown_garbage_and_inference_prefixed_tokens_are_rejected(tmp_path):
    setup_db(tmp_path)

    async def flow():
        return (
            await verify_management_key(MANAGEMENT_KEY_PREFIX + "never-minted"),
            await verify_management_key("garbage"),
            await verify_management_key(""),
            await verify_management_key(INFERENCE_TOKEN_PREFIX + "not-a-mgmt-token"),
        )

    assert run_in_db(tmp_path, flow) == (None, None, None, None)


def test_tampered_token_is_rejected(tmp_path):
    setup_db(tmp_path)

    async def flow():
        member, org_id = await seed_member()
        _, token = await mint_management_key(org_id, member.id, label="t")
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        return await verify_management_key(token), await verify_management_key(tampered)

    valid, forged = run_in_db(tmp_path, flow)
    assert valid is not None
    assert forged is None


def test_membership_backing_still_gates_user_bound_tokens(tmp_path):
    setup_db(tmp_path)

    async def flow():
        member, org_id = await seed_member()
        _, token = await mint_management_key(org_id, member.id, label="t")
        before = await verify_management_key(token)
        membership = await OrgMembership.get((member.id, org_id))
        assert membership is not None
        await membership.delete()
        return before, await verify_management_key(token)

    before, after = run_in_db(tmp_path, flow)
    assert before is not None
    assert after is None


def test_revoking_reaches_only_the_scoped_org(tmp_path):
    """Ownership resolves before anything else, so another org's key is a 404 rather than a revocation."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        instance_headers = cp.headers()
        first = make_org(client, instance_headers, name="org-one")
        second = make_org(client, instance_headers, name="org-two")
        minted = client.post("/v1/org/management-keys", json={"label": "ci"}, headers=cp.headers(org_id=second))
        assert minted.status_code == 200, minted.text
        key_id = minted.json()["data"]["id"]

        assert client.delete(f"/v1/org/management-keys/{key_id}", headers=cp.headers(org_id=first)).status_code == 404
        assert client.delete(f"/v1/org/management-keys/{key_id}", headers=cp.headers(org_id=second)).status_code == 200
