from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from helpers import run_in_db, setup_control_plane

from control_plane.models import AuthSession, User
from control_plane.sessions import SESSION_COOKIE, mint_session, verify_session

CSRF = {"X-Requested-With": "fetch"}
PASSWORD = "hunter2-hunter2"


def _client(cp) -> TestClient:
    return TestClient(cp.app, base_url="https://testserver")


def _make_user(c, root, email="m@example.com", *, admin=False, org=None):
    user = c.post("/v1/instance/users", json={"email": email, "instance_admin": admin}, headers=root).json()["data"]
    if org is not None:
        assert c.put(f"/v1/instance/users/{user['id']}/orgs/{org}", headers=root).status_code == 200
    assert c.put(f"/v1/instance/users/{user['id']}/password", json={"password": PASSWORD}, headers=root).status_code == 200
    return user


def _login(c, email="m@example.com", password=PASSWORD) -> None:
    resp = c.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    assert SESSION_COOKIE in resp.cookies


def test_password_login_sets_cookie_and_cookie_reaches_org_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        c.post("/v1/instance/orgs", json={"id": "o1"}, headers=root)
        user = _make_user(c, root, org="o1")
        resp = c.post("/v1/auth/login", json={"email": "m@example.com", "password": PASSWORD})
        assert resp.status_code == 200
        set_cookie = resp.headers["set-cookie"]
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie
        assert "Secure" in set_cookie
        assert resp.json()["data"]["user_id"] == user["id"]
        assert resp.json()["data"]["orgs"] == ["o1"]

        keys = c.get("/v1/org/keys", headers={**CSRF, "X-Org-Id": "o1"})
        assert keys.status_code == 200
        me = c.get("/v1/auth/me", headers=CSRF)
        assert me.status_code == 200
        assert me.json()["data"]["email"] == "m@example.com"


def test_wrong_password_and_unknown_email_are_indistinguishable_401s(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root)
        wrong = c.post("/v1/auth/login", json={"email": "m@example.com", "password": "nope-nope-nope"})
        unknown = c.post("/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()


def test_cookie_without_csrf_header_or_with_cross_site_fetch_site_is_403(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root, admin=True)
        _login(c)
        assert c.get("/v1/instance/orgs", headers=CSRF).status_code == 200
        assert c.get("/v1/instance/orgs").status_code == 403
        assert c.get("/v1/instance/orgs", headers={**CSRF, "Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.get("/v1/instance/orgs", headers={**CSRF, "Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_bearer_wins_over_cookie_and_a_bad_bearer_never_falls_back(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root, admin=True)
        _login(c)
        assert c.get("/v1/instance/orgs", headers={**CSRF, "authorization": "Bearer ab-mgmt-garbage"}).status_code == 401
        assert c.get("/v1/instance/orgs", headers=root).status_code == 200


def test_x_org_id_requires_membership_and_absence_requires_instance_admin(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        c.post("/v1/instance/orgs", json={"id": "o1"}, headers=root)
        c.post("/v1/instance/orgs", json={"id": "o2"}, headers=root)
        _make_user(c, root, org="o1")
        _login(c)
        assert c.get("/v1/org/keys", headers={**CSRF, "X-Org-Id": "o1"}).status_code == 200
        assert c.get("/v1/org/keys", headers={**CSRF, "X-Org-Id": "o2"}).status_code == 403
        assert c.get("/v1/org/keys", headers={**CSRF, "X-Org-Id": "ghost"}).status_code == 403
        assert c.get("/v1/instance/orgs", headers=CSRF).status_code == 403

        _make_user(c, root, email="root@example.com", admin=True)
        _login(c, email="root@example.com")
        assert c.get("/v1/instance/orgs", headers=CSRF).status_code == 200
        assert c.get("/v1/org/keys", headers={**CSRF, "X-Org-Id": "o1"}).status_code == 200


def test_expired_session_is_401_and_half_life_touch_slides_expiry(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root, admin=True)
        _login(c)

        async def expire():
            row = (await AuthSession.find())[0]
            row.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
            await row.save()

        run_in_db(tmp_path, expire)
        assert c.get("/v1/instance/orgs", headers=CSRF).status_code == 401

    async def sliding():
        slider = await User(id="u-slider", email="slider@example.com", name="slider").save()
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
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root, admin=True)
        _login(c)
        stolen = c.cookies[SESSION_COOKIE]
        assert c.get("/v1/instance/orgs", headers=CSRF).status_code == 200
        out = c.post("/v1/auth/logout", headers=CSRF)
        assert out.status_code == 200
        assert out.json()["data"]["id"].startswith("s-")
        c.cookies.set(SESSION_COOKIE, stolen)
        assert c.get("/v1/instance/orgs", headers=CSRF).status_code == 401


def test_admin_sets_password_and_self_change_requires_current_password(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root)
        _login(c)
        wrong = c.post("/v1/auth/password", json={"current_password": "wrong-wrong-1", "new_password": "next-next-next1"}, headers=CSRF)
        assert wrong.status_code == 403
        ok = c.post("/v1/auth/password", json={"current_password": PASSWORD, "new_password": "next-next-next1"}, headers=CSRF)
        assert ok.status_code == 200
        assert c.post("/v1/auth/login", json={"email": "m@example.com", "password": PASSWORD}).status_code == 401
        _login(c, password="next-next-next1")


def test_login_mints_a_fresh_session_each_time(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root, admin=True)
        _login(c)
        first = c.cookies[SESSION_COOKIE]
        _login(c)
        second = c.cookies[SESSION_COOKIE]
        assert first != second
        assert len(run_in_db(tmp_path, AuthSession.find)) == 2


def test_service_accounts_rejected_from_password_login(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        sa = c.post("/v1/instance/service-accounts", json={"name": "dp"}, headers=root).json()["data"]
        assert c.put(f"/v1/instance/users/{sa['id']}/password", json={"password": "x-x-x-x-x-x-1"}, headers=root).status_code == 422


def test_signup_creates_user_identity_and_session(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        resp = c.post("/v1/auth/signup", json={"email": "New@Example.com", "name": "New", "password": PASSWORD})
        assert resp.status_code == 200, resp.text
        assert SESSION_COOKIE in resp.cookies
        me = resp.json()["data"]
        assert me["email"] == "New@Example.com"
        assert me["instance_admin"] is False
        assert me["orgs"] == []
        assert c.get("/v1/auth/me", headers=CSRF).json()["data"]["user_id"] == me["user_id"]
        assert c.get("/v1/instance/orgs", headers=CSRF).status_code == 403
        c.cookies.clear()
        _login(c, email="New@Example.com")


def test_signup_duplicate_email_is_409(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with _client(cp) as c:
        _make_user(c, root)
        assert c.post("/v1/auth/signup", json={"email": "m@example.com", "password": PASSWORD}).status_code == 409


def test_signup_rejects_short_passwords(tmp_path):
    cp = setup_control_plane(tmp_path)
    with _client(cp) as c:
        assert c.post("/v1/auth/signup", json={"email": "n@example.com", "password": "short"}).status_code == 422
