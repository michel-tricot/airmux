from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, run_in_db, setup_control_plane

from control_plane.models import AuthIdentity, AuthSession, PlaygroundSession, User, set_actor
from control_plane.passwords import hash_password
from control_plane.sessions import SESSION_COOKIE, mint_session, verify_session
from control_plane.throttling import RateLimit, ThrottleConfig

CSRF = {"X-Requested-With": "fetch"}


PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _make_user(c, cp, email="m@example.com", *, admin=False, org=None, tmp_path=None):  # noqa: PLR0913 test helper mirrors the fixtures each test holds
    """Self-signup is the only way a human gets a password; the admin bit is flipped in the database here, since the
    signup that would have claimed the instance belongs to whoever came first."""
    me = c.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": PASSWORD}).json()["data"]
    assert c.post("/api/v1/auth/logout", headers=CSRF).status_code == 200
    c.cookies.clear()
    user = {"id": me["user_id"], **me}
    if org is not None:
        assert c.put(f"/api/v1/organizations/{org}/users/{user['id']}", json={"role": "member"}, headers=cp.headers(org)).status_code == 200
    if admin:
        assert tmp_path is not None

        async def flip():
            account = await User.find_by_id(UUID(user["id"]))
            assert account is not None
            await set_actor(account.id)
            account.instance_role = "owner"
            await account.save()

        run_in_db(tmp_path, flip)
    return user


def _login(c, email="m@example.com", password=PASSWORD) -> None:
    resp = c.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    assert SESSION_COOKIE in resp.cookies


def test_password_login_sets_cookie_and_cookie_reaches_org_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        org_id = make_org(c, root, "o1")
        user = _make_user(c, cp, org=org_id)
        resp = c.post("/api/v1/auth/login", json={"email": "m@example.com", "password": PASSWORD})
        assert resp.status_code == 200
        set_cookie = resp.headers["set-cookie"]
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "Secure" in set_cookie
        assert resp.json()["data"]["user_id"] == user["id"]
        assert resp.json()["data"]["org_count"] == 1

        keys = c.get(f"/api/v1/organizations/{org_id}/workspaces", headers=CSRF)
        assert keys.status_code == 200
        me = c.get("/api/v1/auth/me", headers=CSRF)
        assert me.status_code == 200
        assert me.json()["data"]["email"] == "m@example.com"


def test_wrong_password_and_unknown_email_are_indistinguishable_401s(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _make_user(c, cp)
        wrong = c.post("/api/v1/auth/login", json={"email": "m@example.com", "password": "nope-nope-nope"})
        unknown = c.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()


def test_cookie_without_csrf_header_or_with_cross_site_fetch_site_is_403(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _make_user(c, cp, admin=True, tmp_path=tmp_path)
        _login(c)
        assert c.get("/api/v1/organizations", headers=CSRF).status_code == 200
        assert c.get("/api/v1/organizations").status_code == 403
        assert c.get("/api/v1/organizations", headers={**CSRF, "Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.get("/api/v1/organizations", headers={**CSRF, "Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_bearer_wins_over_cookie_and_a_bad_bearer_never_falls_back(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, cp, admin=True, tmp_path=tmp_path)
        _login(c)
        assert c.get("/api/v1/organizations", headers={**CSRF, "authorization": "Bearer sk-cp-garbage"}).status_code == 401
        assert c.get("/api/v1/organizations", headers=root).status_code == 200


def test_org_paths_require_membership_and_instance_routes_require_an_instance_role(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        _make_user(c, cp, org=o1)
        _login(c)
        assert c.get(f"/api/v1/organizations/{o1}/workspaces", headers=CSRF).status_code == 200
        assert c.get(f"/api/v1/organizations/{o2}/workspaces", headers=CSRF).status_code == 403
        assert c.get("/api/v1/organizations", headers=CSRF).status_code == 403

        _make_user(c, cp, email="root@example.com", admin=True, tmp_path=tmp_path)
        _login(c, email="root@example.com")
        assert c.get("/api/v1/organizations", headers=CSRF).status_code == 200
        assert c.get(f"/api/v1/organizations/{o1}/workspaces", headers=CSRF).status_code == 200


def test_expired_session_is_401_and_half_life_touch_slides_expiry(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _make_user(c, cp, admin=True, tmp_path=tmp_path)
        _login(c)

        async def expire():
            row = (await AuthSession.find())[0]
            row.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
            await row.save()

        run_in_db(tmp_path, expire)
        assert c.get("/api/v1/organizations", headers=CSRF).status_code == 401

    async def sliding():
        slider = User(email="slider@example.com", name="slider")
        await set_actor(slider.id)
        await slider.save()
        user_row, token = await mint_session(slider.id)
        fresh_expiry = user_row.expires_at
        touched = await verify_session(token)
        assert touched is not None
        unmoved = touched.expires_at
        touched.expires_at = datetime.now(tz=UTC) + timedelta(hours=5)
        await touched.save()
        slid = await verify_session(token)
        assert slid is not None
        return fresh_expiry, unmoved, slid.expires_at

    fresh_expiry, unmoved, slid = run_in_db(tmp_path, sliding)
    assert unmoved == fresh_expiry
    assert slid > datetime.now(tz=UTC) + timedelta(hours=11)


def test_logout_revokes_session_and_clears_cookie(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _make_user(c, cp, admin=True, tmp_path=tmp_path)
        _login(c)
        stolen = c.cookies[SESSION_COOKIE]
        assert c.get("/api/v1/organizations", headers=CSRF).status_code == 200
        out = c.post("/api/v1/auth/logout", headers=CSRF)
        assert out.status_code == 200
        assert UUID(out.json()["data"]["id"]).version == 7
        c.cookies.set(SESSION_COOKIE, stolen)
        assert c.get("/api/v1/organizations", headers=CSRF).status_code == 401


def test_logout_revokes_active_playground_session(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        org_id = make_org(c, root)
        workspace_id = make_workspace(c, cp.headers(org_id))
        _make_user(c, cp, admin=True, tmp_path=tmp_path)
        _login(c)
        path = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/playground-session"
        playground_session = c.put(path, headers=CSRF)
        assert playground_session.status_code == 200, playground_session.text

        out = c.post("/api/v1/auth/logout", headers=CSRF)
        assert out.status_code == 200, out.text

    async def revoked():
        session = await PlaygroundSession.find_by_id(UUID(playground_session.json()["data"]["id"]))
        assert session is not None
        return session.revoked

    assert run_in_db(tmp_path, revoked) is True


def test_self_change_requires_current_password(tmp_path):
    cp = setup_control_plane(
        tmp_path, throttling=ThrottleConfig(authentication=RateLimit(burst=10, per_second=10), account=RateLimit(burst=10, per_second=10))
    )
    with _client(cp) as c:
        _make_user(c, cp)
        _login(c)
        wrong = c.post("/api/v1/auth/password", json={"current_password": "wrong-wrong-1", "new_password": "next-next-next1"}, headers=CSRF)
        assert wrong.status_code == 403
        ok = c.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "next-next-next1"}, headers=CSRF)
        assert ok.status_code == 200
        assert c.post("/api/v1/auth/login", json={"email": "m@example.com", "password": PASSWORD}).status_code == 401
        _login(c, password="next-next-next1")


def test_login_mints_a_fresh_session_each_time(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _make_user(c, cp, admin=True, tmp_path=tmp_path)
        _login(c)
        first = c.cookies[SESSION_COOKIE]
        _login(c)
        second = c.cookies[SESSION_COOKIE]
        assert first != second
        assert len(run_in_db(tmp_path, AuthSession.find)) == 2


def test_service_accounts_rejected_from_password_login(tmp_path):
    """Even a service account holding a password identity cannot log in; the exclusion lives in the login path itself."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        sa = c.post("/api/v1/service-accounts", json={"name": "dp"}, headers=root).json()["data"]

        async def plant_password():
            row = await User.find_by_id(UUID(sa["id"]))
            assert row is not None
            await set_actor(row.id)
            await AuthIdentity.set_password_hash(row, hash_password(PASSWORD))

        run_in_db(tmp_path, plant_password)
        assert c.post("/api/v1/auth/login", json={"email": sa["email"], "password": PASSWORD}).status_code == 401


def test_signup_creates_user_identity_and_session(tmp_path):
    """An ordinary signup: an account, an identity, a session, and no authority anywhere.

    The founder goes first because the first signup on a fresh deployment claims it; that path has
    its own tests.
    """
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        c.post("/api/v1/auth/signup", json={"email": "founder@example.com", "name": "Founder", "password": PASSWORD})
        c.cookies.clear()

        resp = c.post("/api/v1/auth/signup", json={"email": "New@Example.com", "name": "New", "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        assert SESSION_COOKIE in resp.cookies
        me = resp.json()["data"]
        assert me["email"] == "new@example.com"
        assert me["instance_role"] is None
        assert me["org_count"] == 0
        assert c.get("/api/v1/auth/me", headers=CSRF).json()["data"]["user_id"] == me["user_id"]
        assert c.get("/api/v1/organizations", headers=CSRF).status_code == 403
        c.cookies.clear()
        _login(c, email="New@Example.com")


def test_signup_duplicate_email_is_409(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        _make_user(c, cp)
        assert c.post("/api/v1/auth/signup", json={"email": "m@example.com", "password": PASSWORD}).status_code == 409


def test_case_variant_signup_cannot_replace_an_existing_password(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        victim_password = "victim-password"
        attacker_password = "attacker-password"
        assert c.post("/api/v1/auth/signup", json={"email": "victim@example.com", "password": victim_password}).status_code == 200
        c.cookies.clear()

        takeover = c.post("/api/v1/auth/signup", json={"email": " Victim@Example.COM ", "password": attacker_password})

        assert takeover.status_code == 409
        assert c.post("/api/v1/auth/login", json={"email": "victim@example.com", "password": victim_password}).status_code == 200
        c.cookies.clear()
        assert c.post("/api/v1/auth/login", json={"email": "victim@example.com", "password": attacker_password}).status_code == 401


def test_signup_rejects_short_passwords(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        assert c.post("/api/v1/auth/signup", json={"email": "n@example.com", "password": "short"}).status_code == 422
