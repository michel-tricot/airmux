from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane
from oidc_helpers import CLIENT_ID, ISSUER, fake_idp

from control_plane.models import AuthIdentity, OrgMembership, User
from control_plane.sessions import SESSION_COOKIE

CSRF = {"X-Requested-With": "fetch"}


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _connection(c, cp, org="o1", *, jit=True, domains=("corp.test",)) -> dict:
    c.post("/v1/orgs", json={"id": org}, headers=cp.headers())
    body = {"issuer": ISSUER, "client_id": CLIENT_ID, "client_secret": "s3cret", "email_domains": list(domains), "jit": jit}
    resp = c.post("/v1/org/sso-connections", json=body, headers=cp.headers(org))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _start(c, connection_id: str) -> tuple[str, str]:
    resp = c.post("/v1/auth/sso/start", json={"connection_id": connection_id})
    assert resp.status_code == 200, resp.text
    url = resp.json()["data"]["authorize_url"]
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"]
    return query["state"][0], query["nonce"][0]


def test_discover_maps_email_domain_to_sso_connection_else_password(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    fake_idp(respx_mock)
    with _client(cp) as c:
        connection = _connection(c, cp)
        sso = c.post("/v1/auth/discover", json={"email": "ada@CORP.TEST"}).json()["data"]
        assert sso == {"method": "sso", "connection_id": connection["id"]}
        password = c.post("/v1/auth/discover", json={"email": "ada@elsewhere.test"}).json()["data"]
        assert password == {"method": "password", "connection_id": None}


def test_sso_connection_create_fetches_discovery_and_hides_client_secret(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    fake_idp(respx_mock)
    with _client(cp) as c:
        connection = _connection(c, cp)
        assert connection["authorization_endpoint"] == f"{ISSUER}/authorize"
        assert connection["token_endpoint"] == f"{ISSUER}/token"
        assert connection["jwks_uri"] == f"{ISSUER}/jwks"
        assert "client_secret" not in connection
        listed = c.get("/v1/org/sso-connections", headers=cp.headers("o1")).json()["data"]
        assert [r["id"] for r in listed] == [connection["id"]]
        assert "client_secret" not in listed[0]

        respx_mock.get("https://other.test/.well-known/openid-configuration").respond(json={"issuer": "https://mismatch.test"})
        bad = c.post(
            "/v1/org/sso-connections",
            json={"issuer": "https://other.test", "client_id": "x", "client_secret": "y", "email_domains": []},
            headers=cp.headers("o1"),
        )
        assert bad.status_code == 422


def test_sso_callback_validates_id_token_and_creates_session(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    arm_token = fake_idp(respx_mock)
    with _client(cp) as c:
        connection = _connection(c, cp)
        state, nonce = _start(c, connection["id"])
        arm_token(nonce)
        resp = c.get("/v1/auth/sso/callback", params={"state": state, "code": "authcode"})
        assert resp.status_code == 200, resp.text
        assert SESSION_COOKIE in resp.cookies
        assert resp.json()["data"]["email"] == "ada@corp.test"
        assert resp.json()["data"]["orgs"] == ["o1"]
        assert c.get("/v1/org/keys", headers={**CSRF, "X-Org-Id": "o1"}).status_code == 200


def test_sso_callback_rejects_replayed_state_bad_nonce_and_wrong_audience(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    arm_token = fake_idp(respx_mock)
    with _client(cp) as c:
        connection = _connection(c, cp)

        state, nonce = _start(c, connection["id"])
        arm_token(nonce)
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 200
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 400

        state, nonce = _start(c, connection["id"])
        arm_token("not-the-nonce")
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 401

        state, nonce = _start(c, connection["id"])
        arm_token(nonce, aud="someone-else")
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 401

        assert c.get("/v1/auth/sso/callback", params={"state": "never-issued", "code": "x"}).status_code == 400


def test_jit_provisions_user_identity_and_membership_exactly_once(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    arm_token = fake_idp(respx_mock)
    with _client(cp) as c:
        connection = _connection(c, cp)
        for _ in range(2):
            state, nonce = _start(c, connection["id"])
            arm_token(nonce)
            assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 200

    users = run_in_db(tmp_path, lambda: User.find(User.email == "ada@corp.test"))
    assert len(users) == 1
    identities = run_in_db(tmp_path, lambda: AuthIdentity.find(AuthIdentity.user_id == users[0].id))
    assert len(identities) == 1
    assert identities[0].subject == "idp-sub-1"
    assert run_in_db(tmp_path, lambda: OrgMembership.get((users[0].id, "o1"))) is not None


def test_jit_disabled_rejects_unknown_subjects_but_links_existing_users(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    arm_token = fake_idp(respx_mock)
    with _client(cp) as c:
        instance_root = cp.headers()
        connection = _connection(c, cp, jit=False)

        state, nonce = _start(c, connection["id"])
        arm_token(nonce)
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 403

        c.post("/v1/instance/users", json={"email": "ada@corp.test"}, headers=instance_root)
        state, nonce = _start(c, connection["id"])
        arm_token(nonce)
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 200


def test_service_accounts_rejected_from_sso_login(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    arm_token = fake_idp(respx_mock)
    with _client(cp) as c:
        instance_root = cp.headers()
        connection = _connection(c, cp)
        sa = c.post("/v1/instance/service-accounts", json={"name": "dp"}, headers=instance_root).json()["data"]
        state, nonce = _start(c, connection["id"])
        arm_token(nonce, email=sa["email"])
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 403


def test_sso_callback_rejects_tokens_signed_by_another_key(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    fake_idp(respx_mock)
    with _client(cp) as c:
        connection = _connection(c, cp)
        state, _nonce = _start(c, connection["id"])
        respx_mock.post(f"{ISSUER}/token").respond(json={"id_token": "eyJhbGciOiJub25lIn0.e30.", "access_token": "at", "token_type": "Bearer"})
        assert c.get("/v1/auth/sso/callback", params={"state": state, "code": "x"}).status_code == 401


def test_signup_rejects_sso_owned_domains(tmp_path, respx_mock):
    cp = setup_control_plane(tmp_path)
    fake_idp(respx_mock)
    with _client(cp) as c:
        _connection(c, cp)
        blocked = c.post("/v1/auth/signup", json={"email": "eve@corp.test", "password": "hunter2-hunter2"})
        assert blocked.status_code == 403
        assert c.post("/v1/auth/signup", json={"email": "eve@elsewhere.test", "password": "hunter2-hunter2"}).status_code == 200
