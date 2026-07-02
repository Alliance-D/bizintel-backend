"""Integration tests for the auth flow against a real database (DATABASE_URL).

These exist because register/login previously failed on every call due to a
passlib/bcrypt version mismatch that no test caught - see the backend
changelog. Registering and authenticating a real user is exactly the
regression this needs to guard against.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import engine
from app.main import app

client = TestClient(app)


def _db_reachable() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not _db_reachable(), reason="DATABASE_URL is not reachable in this environment")


@pytest.fixture
def test_email():
    email = f"pytest_{uuid.uuid4().hex[:12]}@example.com"
    yield email
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app.users WHERE email = :email"), {"email": email})


@requires_db
def test_register_login_and_me_round_trip(test_email):
    register_res = client.post("/api/v1/auth/register", json={
        "full_name": "Pytest User",
        "email": test_email,
        "password": "a-reasonably-long-test-password",
        "role": "entrepreneur",
    })
    assert register_res.status_code == 200, register_res.text
    token = register_res.json()["access_token"]

    login_res = client.post("/api/v1/auth/login", json={"email": test_email, "password": "a-reasonably-long-test-password"})
    assert login_res.status_code == 200, login_res.text
    assert login_res.json()["user"]["email"] == test_email

    me_res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["user"]["email"] == test_email


@requires_db
def test_login_with_wrong_password_is_rejected(test_email):
    client.post("/api/v1/auth/register", json={
        "full_name": "Pytest User", "email": test_email, "password": "correct-password", "role": "entrepreneur",
    })
    res = client.post("/api/v1/auth/login", json={"email": test_email, "password": "wrong-password"})
    assert res.status_code == 401


@requires_db
def test_admin_routes_reject_unauthenticated_requests():
    res = client.get("/api/v1/admin/status")
    assert res.status_code == 401


@requires_db
def test_admin_routes_reject_non_admin_users(test_email):
    register_res = client.post("/api/v1/auth/register", json={
        "full_name": "Regular User", "email": test_email, "password": "a-reasonably-long-test-password", "role": "entrepreneur",
    })
    token = register_res.json()["access_token"]
    res = client.get("/api/v1/admin/status", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
