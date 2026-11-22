from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password, verify_password
from app.models import User


def signup(client, email="Ana@Example.com", password="correct-horse"):
    return client.post("/api/auth/signup", json={"name": " Ana Silva ", "email": email, "password": password})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_round_trip():
    stored = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong-pass", stored)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


def test_signup_then_me(client):
    res = signup(client)
    assert res.status_code == 201
    me = client.get("/api/me", headers=auth(res.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "ana@example.com"  # stored lowercased
    assert me.json()["name"] == "Ana Silva"


def test_login(client):
    signup(client)
    assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "nope-nope"}).status_code == 401
    res = client.post("/api/auth/login", json={"email": "ANA@example.com", "password": "correct-horse"})
    assert res.status_code == 200
    assert client.get("/api/me", headers=auth(res.json()["access_token"])).status_code == 200


def test_duplicate_email_is_rejected(client):
    signup(client)
    assert signup(client, email="ana@EXAMPLE.com").status_code == 409


def test_invited_user_cannot_be_claimed_with_a_password(client):
    with SessionLocal() as db:
        db.add(User(email="invitee@example.com", name="Invitee"))  # an invite: no password, never signed in
        db.commit()
    assert signup(client, email="invitee@example.com").status_code == 409
    res = client.post("/api/auth/login", json={"email": "invitee@example.com", "password": "anything-at-all"})
    assert res.status_code == 401


def test_me_needs_a_valid_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=auth("not-a-jwt")).status_code == 401


def test_signup_can_be_turned_off(client, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
    assert client.get("/api/auth/options").json()["password_signup"] is False
    assert signup(client).status_code == 403
