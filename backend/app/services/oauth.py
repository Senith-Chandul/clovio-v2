"""Sign in with Google or Microsoft, which also connects that person's calendar.

OpenID Connect authorization code flow with PKCE, done with httpx and PyJWT. The browser carries a short-lived signed
cookie between /start and /callback holding the state, nonce and PKCE verifier, so a callback can't be replayed or
forged from another browser. Refresh tokens are stored Fernet-encrypted.
"""

import base64
import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ConnectedAccount, Provider, User, utcnow

log = logging.getLogger(__name__)

# Consumer Microsoft accounts (Outlook.com, Hotmail) sign in through this tenant; Microsoft has verified their email.
MS_PERSONAL_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"
STATE_MINUTES = 10
LINK_MINUTES = 5


@dataclass(frozen=True)
class Endpoints:
    authorize: str
    token: str
    jwks: str
    scopes: tuple[str, ...]
    extra: dict


ENDPOINTS = {
    Provider.google: Endpoints(
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "https://www.googleapis.com/oauth2/v3/certs",
        ("openid", "email", "profile",
         "https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.freebusy"),
        # Google sends a refresh token only when the consent screen is shown.
        {"access_type": "offline", "prompt": "consent"},
    ),
    Provider.microsoft: Endpoints(
        # "common": work, school and personal accounts all work.
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "https://login.microsoftonline.com/common/discovery/v2.0/keys",
        ("openid", "email", "profile", "offline_access", "https://graph.microsoft.com/Calendars.ReadWrite"),
        {"prompt": "select_account"},
    ),
}

LABEL = {Provider.google: "Google", Provider.microsoft: "Microsoft"}

# One client for every call to Google and Microsoft; tests swap in a mock transport.
http = httpx.Client(timeout=15)


class OAuthError(Exception):
    """The provider refused or didn't answer. `revoked`: the grant itself is dead, so the person must reconnect."""

    def __init__(self, message: str, revoked: bool = False):
        super().__init__(message)
        self.revoked = revoked


def credentials(provider: Provider) -> tuple[str, str]:
    if provider == Provider.google:
        return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    return settings.MICROSOFT_CLIENT_ID, settings.MICROSOFT_CLIENT_SECRET


def enabled(provider: Provider) -> bool:
    return all(credentials(provider))


def redirect_uri(provider: Provider) -> str:
    return f"{settings.API_URL}/api/auth/{provider}/callback"


# ── Encrypted tokens ────────────────────────────────────────────────────────


def _fernet() -> Fernet:
    key = settings.TOKEN_KEY or base64.urlsafe_b64encode(hashlib.sha256(b"clovio-tokens:" + settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def unseal(text: str | None) -> str | None:
    """None when there's nothing stored or the key changed, which means the person reconnects."""
    try:
        return _fernet().decrypt(text.encode()).decode() if text else None
    except InvalidToken:
        return None


# ── The flow ────────────────────────────────────────────────────────────────


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def safe_next(path: str | None) -> str:
    # Only paths inside the app, so the redirect can't be pointed at another site.
    return path if path and path.startswith("/") and not path.startswith("//") and "\\" not in path else "/"


def link_ticket(user_id: uuid.UUID) -> str:
    """Lets a signed-in person's browser start a flow that adds a calendar to their account. No `sub`, so it can't
    be used as a login token."""
    exp = datetime.now(UTC) + timedelta(minutes=LINK_MINUTES)
    return jwt.encode({"purpose": "link", "link": str(user_id), "exp": exp}, settings.SECRET_KEY, algorithm="HS256")


def start(provider: Provider, next_path: str | None, ticket: str | None) -> tuple[str, str]:
    """The provider's sign-in URL, and the cookie value to set with it."""
    if not enabled(provider):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{LABEL[provider]} sign-in isn't set up here.")
    link = None
    if ticket:
        try:
            claims = jwt.decode(ticket, settings.SECRET_KEY, algorithms=["HS256"])
            assert claims.get("purpose") == "link"
            link = claims["link"]
        except (jwt.PyJWTError, KeyError, AssertionError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That link has expired. Go back to Settings and try again.")
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    cookie = jwt.encode(
        {"purpose": "oauth", "provider": str(provider), "state": state, "nonce": nonce, "verifier": verifier,
         "next": safe_next(next_path), "link": link, "exp": datetime.now(UTC) + timedelta(minutes=STATE_MINUTES)},
        settings.SECRET_KEY, algorithm="HS256",
    )
    ends = ENDPOINTS[provider]
    params = {
        "client_id": credentials(provider)[0],
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": " ".join(ends.scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
        **ends.extra,
    }
    return f"{ends.authorize}?{urlencode(params)}", cookie


def read_cookie(provider: Provider, cookie: str | None, state: str | None) -> dict:
    expired = HTTPException(status.HTTP_400_BAD_REQUEST, "Sign-in took too long or was started in another browser. Try again.")
    try:
        data = jwt.decode(cookie or "", settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise expired
    if data.get("purpose") != "oauth" or data.get("provider") != provider or not secrets.compare_digest(data.get("state", ""), state or ""):
        raise expired
    return data


def exchange(provider: Provider, form: dict) -> dict:
    """A call to the provider's token endpoint: a code for tokens, or a refresh token for a new access token."""
    client_id, secret = credentials(provider)
    try:
        res = http.post(ENDPOINTS[provider].token, data={"client_id": client_id, "client_secret": secret, **form})
    except httpx.HTTPError as error:
        raise OAuthError(f"{LABEL[provider]} didn't answer: {error}") from error
    body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
    if res.status_code != 200 or "access_token" not in body:
        log.warning("%s token endpoint said %s: %s", provider, res.status_code, body.get("error"))
        raise OAuthError(body.get("error_description") or body.get("error") or f"HTTP {res.status_code}",
                         revoked=body.get("error") == "invalid_grant")
    return body


_jwks: dict[Provider, jwt.PyJWKClient] = {}


def _signing_key(provider: Provider, id_token: str):
    client = _jwks.setdefault(provider, jwt.PyJWKClient(ENDPOINTS[provider].jwks, cache_keys=True))
    return client.get_signing_key_from_jwt(id_token).key


def id_claims(provider: Provider, id_token: str, nonce: str) -> dict:
    """The ID token's claims, after checking its signature, audience, issuer, expiry and nonce."""
    try:
        claims = jwt.decode(
            id_token, _signing_key(provider, id_token), algorithms=["RS256"], audience=credentials(provider)[0],
            options={"require": ["exp", "iat", "sub", "iss"]}, leeway=60,
        )
    except jwt.PyJWTError as error:
        raise OAuthError(f"The sign-in token didn't check out ({error}).") from error
    if provider == Provider.google:
        issuer_ok = claims["iss"] in ("https://accounts.google.com", "accounts.google.com")
    else:
        issuer_ok = claims["iss"] == f"https://login.microsoftonline.com/{claims.get('tid')}/v2.0"
    if not issuer_ok or not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OAuthError("The sign-in token didn't check out.")
    return claims


def verified_email(provider: Provider, claims: dict) -> str | None:
    """The email, only if the provider vouches for it. Otherwise anyone with their own Microsoft tenant could name
    themselves after an invited person and take over their account."""
    email = (claims.get("email") or "").strip().lower()
    if provider == Provider.google:
        ok = claims.get("email_verified") is True
    else:
        ok = claims.get("tid") == MS_PERSONAL_TENANT or str(claims.get("xms_edov")).lower() in ("true", "1")
    return email if email and ok else None


def may_join(email: str) -> bool:
    """Whether someone not invited to any project may still create an account (settings.NEW_ACCOUNT_EMAILS)."""
    allowed = settings.NEW_ACCOUNT_EMAILS
    return "*" in allowed or email in allowed or "@" + email.rsplit("@", 1)[-1] in allowed


def finish(db: Session, provider: Provider, code: str, cookie: dict) -> tuple[User, bool]:
    """Complete the flow: the person signed in (or the account linked to them), and whether it was a link."""
    tokens = exchange(provider, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(provider),
                                 "code_verifier": cookie["verifier"]})
    claims = id_claims(provider, tokens.get("id_token", ""), cookie["nonce"])
    subject = claims["sub"]
    email = verified_email(provider, claims)
    account = db.scalar(select(ConnectedAccount).where(ConnectedAccount.provider == provider, ConnectedAccount.subject == subject))

    if cookie.get("link"):
        user = db.get(User, uuid.UUID(cookie["link"]))
        if user is None:
            raise OAuthError("Your session has ended. Sign in again.")
        if account and account.user_id != user.id:
            raise OAuthError(f"That {LABEL[provider]} account is already connected to someone else in Clovio.")
    elif account:
        user = db.get(User, account.user_id)
    else:
        if email is None:
            raise OAuthError(f"{LABEL[provider]} didn't confirm this account's email, so Clovio can't sign you in with it.")
        # A verified email claims the invited person's row, so the work already given to them is theirs.
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            if not may_join(email):
                raise OAuthError("You haven't been added to Clovio yet. Ask whoever runs your project to add you, then sign in again.")
            user = User(email=email, name=claims.get("name") or email.split("@")[0])
            db.add(user)
            db.flush()

    if not cookie.get("link"):
        if user.last_login_at is None and claims.get("name"):
            user.name = claims["name"]  # an invite's name was typed by someone else; theirs wins on first sign-in
        user.last_login_at = utcnow()

    # One calendar per provider per person: a newly chosen account replaces the old one.
    db.execute(delete(ConnectedAccount).where(
        ConnectedAccount.user_id == user.id, ConnectedAccount.provider == provider, ConnectedAccount.subject != subject))
    if account is None:
        account = ConnectedAccount(user_id=user.id, provider=provider, subject=subject, email=email or claims.get("email") or "")
        db.add(account)
    account.email = email or account.email
    if tokens.get("refresh_token"):
        account.refresh_token = seal(tokens["refresh_token"])
    account.scopes = tokens.get("scope", "").split()
    account.needs_reconnect = account.refresh_token is None
    db.flush()
    _remember(account.id, tokens)
    return user, bool(cookie.get("link"))


# ── Access tokens for calendar calls ────────────────────────────────────────

# shortcut: access tokens are cached per server process (each worker refreshes its own); store them encrypted
# in connected_accounts if refreshes ever hit the providers' rate limits.
_access: dict[uuid.UUID, tuple[str, datetime]] = {}


def _remember(account_id: uuid.UUID, tokens: dict) -> None:
    expires = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in") or 3600) - 120)
    _access[account_id] = (tokens["access_token"], expires)


def access_token(db: Session, account: ConnectedAccount) -> str:
    """A working access token, refreshed when needed. A refresh token that stopped working (revoked, or Google's
    7-day limit in testing mode) marks the account for reconnecting, committed straight away so the flag sticks."""
    cached = _access.get(account.id)
    if cached and cached[1] > datetime.now(UTC):
        return cached[0]
    refresh = unseal(account.refresh_token)
    try:
        if refresh is None:
            raise OAuthError("No refresh token stored.", revoked=True)
        tokens = exchange(account.provider, {"grant_type": "refresh_token", "refresh_token": refresh})
    except OAuthError as error:
        if error.revoked:
            account.needs_reconnect = True
            db.commit()
        raise
    if tokens.get("refresh_token"):  # Microsoft hands out a new one each time
        account.refresh_token = seal(tokens["refresh_token"])
        db.commit()
    _remember(account.id, tokens)
    return tokens["access_token"]
