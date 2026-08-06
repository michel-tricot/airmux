from __future__ import annotations

from helpers import run_in_db, setup_control_plane

from contract import INFERENCE_TOKEN_PREFIX, token_hash
from control_plane.models import MgmtToken, Org, OrgMembership, User
from control_plane.tokens import MANAGEMENT_TOKEN_PREFIX, mint_mgmt_key, verify_management_token


async def _admin(user_id: str = "u-admin") -> User:
    return await User(id=user_id, email=f"{user_id}@example.com", name=user_id, instance_admin=True).save()


async def _member(user_id: str, org_id: str) -> User:
    user = await User(id=user_id, email=f"{user_id}@example.com", name=user_id).save()
    await Org(id=org_id, name=org_id).save()
    await OrgMembership(user_id=user_id, org_id=org_id).save()
    return user


def test_minted_token_has_prefix_and_stored_hash(tmp_path):
    setup_control_plane(tmp_path)

    async def mint():
        await _admin()
        token_id, token = await mint_mgmt_key(None, "u-admin")
        return token, await MgmtToken.get(token_id)

    token, row = run_in_db(tmp_path, mint)
    assert token.startswith(MANAGEMENT_TOKEN_PREFIX)
    assert row.token_hash == token_hash(token)
    assert token not in row.model_dump_json()


def test_verify_accepts_a_minted_token_and_builds_claims_from_the_row(tmp_path):
    setup_control_plane(tmp_path)

    async def flow():
        await _member("u-1", "o1")
        token_id, token = await mint_mgmt_key("o1", "u-1")
        return token_id, await verify_management_token(token)

    token_id, claims = run_in_db(tmp_path, flow)
    assert claims is not None
    assert claims.token_id == token_id
    assert claims.org_id == "o1"
    assert claims.user_id == "u-1"


def test_revoked_row_is_rejected(tmp_path):
    setup_control_plane(tmp_path)

    async def flow():
        await _admin()
        token_id, token = await mint_mgmt_key(None, "u-admin")
        before = await verify_management_token(token)
        row = await MgmtToken.get(token_id)
        assert row is not None
        row.revoked = True
        await row.save()
        return before, await verify_management_token(token)

    before, after = run_in_db(tmp_path, flow)
    assert before is not None
    assert after is None


def test_unknown_garbage_and_inference_prefixed_tokens_are_rejected(tmp_path):
    setup_control_plane(tmp_path)

    async def flow():
        return (
            await verify_management_token(MANAGEMENT_TOKEN_PREFIX + "never-minted"),
            await verify_management_token("garbage"),
            await verify_management_token(""),
            await verify_management_token(INFERENCE_TOKEN_PREFIX + "not-a-mgmt-token"),
        )

    assert run_in_db(tmp_path, flow) == (None, None, None, None)


def test_tampered_token_is_rejected(tmp_path):
    setup_control_plane(tmp_path)

    async def flow():
        await _admin()
        _, token = await mint_mgmt_key(None, "u-admin")
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        return await verify_management_token(token), await verify_management_token(tampered)

    valid, forged = run_in_db(tmp_path, flow)
    assert valid is not None
    assert forged is None


def test_membership_backing_still_gates_user_bound_tokens(tmp_path):
    setup_control_plane(tmp_path)

    async def flow():
        await _member("u-1", "o1")
        _, token = await mint_mgmt_key("o1", "u-1")
        before = await verify_management_token(token)
        membership = await OrgMembership.get(("u-1", "o1"))
        assert membership is not None
        await membership.delete()
        return before, await verify_management_token(token)

    before, after = run_in_db(tmp_path, flow)
    assert before is not None
    assert after is None
