from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, run_in_db, setup_control_plane

from control_plane.models import AuthSession
from control_plane.sessions import SESSION_COOKIE

CSRF = {"X-Requested-With": "fetch"}
PASSWORD = "original-password"


@pytest.mark.parametrize("credential", ["session", "management_key"])
def test_password_change_revokes_browser_sessions_but_preserves_management_keys(tmp_path, credential):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app, base_url="https://testserver") as client:
        signup = client.post("/api/v1/auth/signup", json={"email": "recovery@example.com", "password": PASSWORD})
        assert signup.status_code == 200
        first_cookie = client.cookies[SESSION_COOKIE]
        org_id = make_org(client, CSRF)
        key = client.post(f"/api/v1/orgs/{org_id}/management-keys", headers=CSRF, json={"label": "retained", "permissions": ["catalog.read"]})
        assert key.status_code == 200
        bearer = {"authorization": f"Bearer {key.json()['data']['token']}"}
        assert client.post("/api/v1/auth/login", json={"email": "recovery@example.com", "password": PASSWORD}).status_code == 200
        second_cookie = client.cookies[SESSION_COOKIE]
        changed = client.post(
            "/api/v1/auth/password",
            headers=CSRF if credential == "session" else bearer,
            json={"current_password": PASSWORD, "new_password": "replacement-password"},
        )
        assert changed.status_code == 200
        if credential == "session":
            assert client.cookies[SESSION_COOKIE] not in {first_cookie, second_cookie}
            assert client.get("/api/v1/auth/me", headers=CSRF).status_code == 200
        else:
            assert "set-cookie" not in changed.headers
        sessions = run_in_db(tmp_path, AuthSession.find)
        assert len(sessions) == (1 if credential == "session" else 0)
        client.cookies.clear()
        for cookie in (first_cookie, second_cookie):
            assert client.get("/api/v1/auth/me", headers={**CSRF, "cookie": f"{SESSION_COOKIE}={cookie}"}).status_code == 401
        assert client.get("/api/v1/auth/me", headers=bearer).status_code == 200
        assert client.post("/api/v1/auth/login", json={"email": "recovery@example.com", "password": PASSWORD}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"email": "recovery@example.com", "password": "replacement-password"}).status_code == 200


def test_password_change_rejects_a_concurrent_login_using_the_old_password(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app, base_url="https://testserver") as client:
        signup = client.post("/api/v1/auth/signup", json={"email": "concurrent@example.com", "password": PASSWORD})
        signup.raise_for_status()
        current_cookie = signup.cookies[SESSION_COOKIE]
        barrier = Barrier(2)

        def change_password():
            barrier.wait()
            return client.post(
                "/api/v1/auth/password",
                headers={**CSRF, "cookie": f"{SESSION_COOKIE}={current_cookie}"},
                json={"current_password": PASSWORD, "new_password": "replacement-password"},
            )

        def log_in():
            barrier.wait()
            return client.post("/api/v1/auth/login", json={"email": "concurrent@example.com", "password": PASSWORD})

        with ThreadPoolExecutor(max_workers=2) as executor:
            changed, logged_in = (future.result() for future in (executor.submit(change_password), executor.submit(log_in)))

        assert changed.status_code == 200
        assert logged_in.status_code in {200, 401}
        competing_cookie = logged_in.cookies.get(SESSION_COOKIE)
        if logged_in.status_code == 200:
            assert competing_cookie is not None

    if competing_cookie is not None:
        with TestClient(cp.app, base_url="https://testserver") as verifier:
            headers = {**CSRF, "cookie": f"{SESSION_COOKIE}={competing_cookie}"}
            assert verifier.get("/api/v1/auth/me", headers=headers).status_code == 401
