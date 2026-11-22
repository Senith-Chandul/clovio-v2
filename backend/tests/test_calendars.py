"""Sign-in with Google and Microsoft, connected calendars and meetings, against fake provider endpoints."""

import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import ConnectedAccount, Provider
from app.services import calendars, oauth

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def fake(monkeypatch):
    """Google and Microsoft as configured providers, with their endpoints answered by `fake.routes`."""
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"):
        monkeypatch.setattr(settings, name, name.lower())
    monkeypatch.setattr(oauth, "_signing_key", lambda provider, token: KEY.public_key())
    monkeypatch.setattr(settings, "NEW_ACCOUNT_EMAILS", ["*"])
    monkeypatch.setattr(oauth, "_access", {})
    monkeypatch.setattr(calendars, "_busy", {})
    state = SimpleNamespace(calls=[], routes={}, claims={})

    def handler(request: httpx.Request) -> httpx.Response:
        state.calls.append(request)
        for (method, prefix), answer in state.routes.items():
            if request.method == method and str(request.url).startswith(prefix):
                status, body = answer(request) if callable(answer) else answer
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={"error": "not faked"})

    monkeypatch.setattr(oauth, "http", httpx.Client(transport=httpx.MockTransport(handler)))
    return state


def id_token(provider, nonce, **claims):
    base = {"iss": "https://accounts.google.com", "aud": "google_client_id"} if provider == "google" else {
        "iss": f"https://login.microsoftonline.com/{claims.get('tid', 'tenant-1')}/v2.0", "aud": "microsoft_client_id"}
    now = int(time.time())
    return jwt.encode({**base, "iat": now, "exp": now + 600, "nonce": nonce, **claims}, KEY, algorithm="RS256")


def sign_in(client, fake, provider, claims, link=None, refresh="refresh-1"):
    """Go through /start and /callback as a browser would; returns the callback's redirect target."""
    params = {"next": "/my"} | ({"link": link} if link else {})
    start = client.get(f"/api/auth/{provider}/start", params=params, follow_redirects=False)
    assert start.status_code == 302, start.text
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["redirect_uri"] == [f"http://localhost:8000/api/auth/{provider}/callback"]
    token_url = oauth.ENDPOINTS[Provider(provider)].token
    fake.routes[("POST", token_url)] = (200, {
        "access_token": "access-1", "refresh_token": refresh, "expires_in": 3600, "scope": "openid email",
        "id_token": id_token(provider, query["nonce"][0], **claims)})
    back = client.get(f"/api/auth/{provider}/callback", params={"code": "code-1", "state": query["state"][0]}, follow_redirects=False)
    assert back.status_code == 302
    return back.headers["location"]


def fragment(location):
    return {k: v[0] for k, v in parse_qs(urlparse(location).fragment).items()}


def bearer(location):
    return {"Authorization": f"Bearer {fragment(location)['token']}"}


def test_google_sign_in_claims_the_invite_and_stores_the_token_encrypted(client, login, fake):
    owner = login("owner@example.com")
    pid = client.post("/api/projects", json={"name": "Gala"}, headers=owner).json()["id"]
    client.post(f"/api/projects/{pid}/members", json={"email": "ana@example.com", "name": "ana?"}, headers=owner)

    where = sign_in(client, fake, "google", {"sub": "g-1", "email": "Ana@Example.com", "email_verified": True, "name": "Ana Silva"})
    assert where.startswith("http://localhost:5173/auth/callback#") and fragment(where)["next"] == "/my"
    me = client.get("/api/me", headers=bearer(where)).json()
    assert (me["email"], me["name"]) == ("ana@example.com", "Ana Silva")
    assert [p["name"] for p in client.get("/api/projects", headers=bearer(where)).json()] == ["Gala"]

    with SessionLocal() as db:
        account = db.query(ConnectedAccount).one()
        assert account.refresh_token != "refresh-1" and oauth.unseal(account.refresh_token) == "refresh-1"
    # The same Google account signs in to the same person, by its subject, even if the email changed.
    again = sign_in(client, fake, "google", {"sub": "g-1", "email": "ana.new@example.com", "email_verified": True})
    assert client.get("/api/me", headers=bearer(again)).json()["id"] == me["id"]


def test_unverified_emails_and_bad_tokens_are_refused(client, fake):
    google = sign_in(client, fake, "google", {"sub": "g-2", "email": "eve@example.com", "email_verified": False})
    assert google.startswith("http://localhost:5173/login#") and "confirm" in fragment(google)["error"]
    # A work account's email counts only with xms_edov; a personal Microsoft account's always does.
    work = sign_in(client, fake, "microsoft", {"sub": "m-1", "tid": "tenant-1", "email": "eve@example.com"})
    assert "error" in fragment(work)
    work_ok = sign_in(client, fake, "microsoft", {"sub": "m-2", "tid": "tenant-1", "email": "raj@example.com", "xms_edov": True})
    personal = sign_in(client, fake, "microsoft", {"sub": "m-3", "tid": oauth.MS_PERSONAL_TENANT, "email": "kim@example.com"})
    assert "token" in fragment(work_ok) and "token" in fragment(personal)

    # A callback without the browser's cookie (started elsewhere, or forged) goes nowhere.
    client.cookies.clear()
    forged = client.get("/api/auth/google/callback", params={"code": "x", "state": "y"}, follow_redirects=False)
    assert "error" in fragment(forged.headers["location"])


def test_id_token_checks(fake):
    good = id_token("google", "n-1", sub="g")
    assert oauth.id_claims(Provider.google, good, "n-1")["sub"] == "g"
    for token, nonce in [
        (good, "other-nonce"),
        (id_token("google", "n-1", sub="g", aud="someone-else"), "n-1"),
        (id_token("google", "n-1", sub="g", iss="https://evil.example.com"), "n-1"),
        (id_token("microsoft", "n-1", sub="m", tid="t-1", iss="https://login.microsoftonline.com/t-2/v2.0"), "n-1"),
    ]:
        provider = Provider.microsoft if "microsoftonline" in jwt.decode(token, options={"verify_signature": False})["iss"] else Provider.google
        with pytest.raises(oauth.OAuthError):
            oauth.id_claims(provider, token, nonce)


def test_connect_a_calendar_then_meet_then_cancel(client, login, fake):
    owner, member = login("owner@example.com", "Olu Owner"), login("member@example.com", "Mia Member")
    pid = client.post("/api/projects", json={"name": "Gala"}, headers=owner).json()["id"]
    mia = client.post(f"/api/projects/{pid}/members", json={"email": "member@example.com"}, headers=owner).json()["user_id"]
    body = {"title": "Venue walk-through", "starts_at": "2026-11-30T04:30:00Z", "minutes": 60, "attendee_ids": [mia]}
    assert client.post(f"/api/projects/{pid}/meetings", json=body, headers=owner).status_code == 409  # no calendar yet

    connect = client.post("/api/calendars/google/connect", headers=owner).json()["url"]
    ticket = parse_qs(urlparse(connect).query)["link"][0]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401  # not a login
    where = sign_in(client, fake, "google", {"sub": "g-9", "email": "olu@gmail.example.com", "email_verified": True}, link=ticket)
    assert where == "http://localhost:5173/settings#connected=google"
    cals = client.get("/api/calendars", headers=owner).json()
    assert cals["accounts"] == [{"provider": "google", "email": "olu@gmail.example.com", "needs_reconnect": False}]
    assert set(cals["available"]) == {"google", "microsoft"}

    fake.routes[("POST", f"{calendars.GOOGLE}/calendars/primary/events")] = (200, {"id": "evt-1"})
    made = client.post(f"/api/projects/{pid}/meetings", json=body, headers=owner)
    assert made.status_code == 201, made.text
    sent = fake.calls[-1]
    assert sent.url.params["sendUpdates"] == "all" and sent.headers["authorization"] == "Bearer access-1"
    assert json.loads(sent.content)["attendees"] == [{"email": "member@example.com"}]
    assert [m["title"] for m in client.get(f"/api/projects/{pid}/meetings", headers=member).json()] == ["Venue walk-through"]
    note = client.get("/api/notifications", headers=member).json()["items"][0]["text"]
    assert note == "Olu Owner invited you to “Venue walk-through” on Mon 30 Nov, 04:30."  # Mia's zone is UTC

    meeting = made.json()["id"]
    assert client.delete(f"/api/meetings/{meeting}", headers=member).status_code == 403  # not the organiser
    fake.routes[("DELETE", f"{calendars.GOOGLE}/calendars/primary/events/evt-1")] = (204, {})
    assert client.delete(f"/api/meetings/{meeting}", headers=owner).status_code == 204
    assert client.get(f"/api/projects/{pid}/meetings", headers=owner).json() == []


def test_a_dead_refresh_token_asks_the_person_to_reconnect(client, login, fake):
    owner = login("owner@example.com")
    pid = client.post("/api/projects", json={"name": "Gala"}, headers=owner).json()["id"]
    ticket = parse_qs(urlparse(client.post("/api/calendars/google/connect", headers=owner).json()["url"]).query)["link"][0]
    sign_in(client, fake, "google", {"sub": "g-5", "email": "o@example.com", "email_verified": True}, link=ticket)
    oauth._access.clear()  # the access token ran out
    fake.routes[("POST", oauth.ENDPOINTS[Provider.google].token)] = (400, {"error": "invalid_grant"})
    body = {"title": "Sync", "starts_at": "2026-11-30T04:30:00Z", "minutes": 30, "attendee_ids": []}
    res = client.post(f"/api/projects/{pid}/meetings", json=body, headers=owner)
    assert res.status_code == 409 and "Reconnect" in res.json()["detail"]
    assert client.get("/api/calendars", headers=owner).json()["accounts"][0]["needs_reconnect"] is True


def test_outlook_busy_times_skip_free_events_and_follow_pages(fake):
    account = ConnectedAccount(id=uuid.uuid4(), provider=Provider.microsoft, subject="m", email="x@example.com")
    oauth._access[account.id] = ("access-ms", datetime.now(UTC) + timedelta(hours=1))
    page2 = f"{calendars.GRAPH}/me/calendarView?page=2"

    def view(request):
        if "page=2" in str(request.url):
            return 200, {"value": [{"start": {"dateTime": "2026-11-24T09:00:00.0000000"}, "end": {"dateTime": "2026-11-24T10:00:00.0000000"}, "showAs": "tentative"}]}
        assert request.headers["prefer"] == 'outlook.timezone="UTC"'
        return 200, {"value": [
            {"start": {"dateTime": "2026-11-23T09:00:00.0000000"}, "end": {"dateTime": "2026-11-23T10:30:00.0000000"}, "showAs": "busy"},
            {"start": {"dateTime": "2026-11-23T12:00:00.0000000"}, "end": {"dateTime": "2026-11-23T13:00:00.0000000"}, "showAs": "free"},
        ], "@odata.nextLink": page2}

    fake.routes[("GET", f"{calendars.GRAPH}/me/calendarView")] = view
    got = calendars._fetch_busy(None, account, datetime(2026, 11, 23, tzinfo=UTC), datetime(2026, 11, 25, tzinfo=UTC))
    assert [(s.isoformat(), e.isoformat()) for s, e in got] == [
        ("2026-11-23T09:00:00+00:00", "2026-11-23T10:30:00+00:00"),
        ("2026-11-24T09:00:00+00:00", "2026-11-24T10:00:00+00:00"),
    ]


def test_busy_hours_count_only_the_local_working_day():
    utc = lambda *a: datetime(*a, tzinfo=UTC)  # noqa: E731
    # Colombo is UTC+5:30, so its 9:00-17:00 is 3:30-11:30 UTC.
    hours = calendars.busy_hours_by_day(
        [(utc(2026, 11, 23, 4, 30), utc(2026, 11, 23, 6, 30)), (utc(2026, 11, 23, 10, 30), utc(2026, 11, 23, 14, 0))],
        "Asia/Colombo", date(2026, 11, 23), days=2)
    assert hours == (3.0, 0.0)


def test_suggested_times_avoid_everyones_busy_time(client):
    monday_7am = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)
    me = SimpleNamespace(id=uuid.uuid4(), name="Olu", timezone="UTC")
    them = SimpleNamespace(id=uuid.uuid4(), name="Mia", timezone="UTC")
    nobody_knows = SimpleNamespace(id=uuid.uuid4(), name="Ravi", timezone="UTC")
    calendars._busy[me.id] = (monday_7am, [(monday_7am.replace(hour=9), monday_7am.replace(hour=10, minute=30))])
    calendars._busy[them.id] = (monday_7am, [(monday_7am.replace(hour=11), monday_7am.replace(hour=12))])
    with SessionLocal() as db:
        slots, unknown = calendars.suggest(db, me, [them, nobody_knows], 60, now=monday_7am)
    assert [s.strftime("%a %H:%M") for s in slots] == ["Mon 12:00", "Mon 14:00", "Tue 09:00", "Tue 11:00", "Wed 09:00"]
    assert unknown == ["Ravi"]

    friday_late = datetime(2026, 11, 27, 16, 45, tzinfo=UTC)
    with SessionLocal() as db:
        later, _ = calendars.suggest(db, me, [], 30, now=friday_late, count=1)
    assert later[0].strftime("%a %H:%M") == "Mon 09:00"  # not tonight, not the weekend


def test_sign_in_is_invite_only_unless_listed(client, login, fake, monkeypatch):
    monkeypatch.setattr(settings, "NEW_ACCOUNT_EMAILS", ["boss@example.com", "@crew.example.com"])
    owner = login("owner@example.com")
    pid = client.post("/api/projects", json={"name": "Gala"}, headers=owner).json()["id"]
    client.post(f"/api/projects/{pid}/members", json={"email": "guest@example.com"}, headers=owner)

    def google(sub, email):
        return fragment(sign_in(client, fake, "google", {"sub": sub, "email": email, "email_verified": True}))

    assert "added to Clovio" in google("g-1", "stranger@example.com")["error"]
    assert "token" in google("g-2", "guest@example.com")  # invited
    assert "token" in google("g-3", "boss@example.com")  # listed
    assert "token" in google("g-4", "anyone@crew.example.com")  # listed domain
    assert "token" in google("g-2", "guest@example.com")  # and back again by subject
