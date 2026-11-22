from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token, get_current_user, hash_password, verify_password
from app.models import Provider, User, utcnow
from app.schemas import MeIn, Name, UserOut
from app.services import oauth

router = APIRouter(prefix="/api", tags=["auth"])


class AuthOptions(BaseModel):
    password_signup: bool
    google: bool
    microsoft: bool


class SignupIn(BaseModel):
    name: Name
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=200)]


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.get("/auth/options", response_model=AuthOptions)
def auth_options():
    """What the sign-in page can offer, so it never shows a button that doesn't work."""
    return AuthOptions(password_signup=settings.ALLOW_SIGNUP, google=oauth.enabled(Provider.google),
                       microsoft=oauth.enabled(Provider.microsoft))


COOKIE = "clovio_oauth"


@router.get("/auth/{provider}/start", include_in_schema=False)
def oauth_start(provider: Provider, next: str | None = None, link: str | None = None):
    """The browser comes here (a link, not an API call), and goes on to Google or Microsoft."""
    try:
        url, cookie = oauth.start(provider, next, link)
    except HTTPException as error:
        page = "settings" if link else "login"
        return RedirectResponse(f"{settings.FRONTEND_URL}/{page}#{urlencode({'error': error.detail})}", status.HTTP_302_FOUND)
    res = RedirectResponse(url, status.HTTP_302_FOUND)
    res.set_cookie(COOKIE, cookie, max_age=oauth.STATE_MINUTES * 60, path="/api/auth", httponly=True,
                   secure=settings.API_URL.startswith("https://"), samesite="lax")
    return res


@router.get("/auth/{provider}/callback", include_in_schema=False)
def oauth_callback(provider: Provider, request: Request, code: str | None = None, state: str | None = None,
                   error: str | None = None, db: Session = Depends(get_db)):
    """Where Google or Microsoft sends the browser back. On to the web app with a login token in the URL fragment
    (fragments aren't sent to servers, so it stays out of logs), or with what went wrong."""
    linking = False
    try:
        data = oauth.read_cookie(provider, request.cookies.get(COOKIE), state)
        linking = bool(data.get("link"))
        if error or not code:
            raise oauth.OAuthError("Sign-in was cancelled." if error == "access_denied" else f"{oauth.LABEL[provider]} said: {error or 'no code'}.")
        user, linking = oauth.finish(db, provider, code, data)
        db.commit()
        if linking:
            target = f"{settings.FRONTEND_URL}/settings#{urlencode({'connected': provider})}"
        else:
            target = f"{settings.FRONTEND_URL}/auth/callback#{urlencode({'token': create_token(user.id), 'next': data['next']})}"
    except (HTTPException, oauth.OAuthError) as failure:
        db.rollback()
        message = failure.detail if isinstance(failure, HTTPException) else str(failure)
        target = f"{settings.FRONTEND_URL}/{'settings' if linking else 'login'}#{urlencode({'error': message})}"
    res = RedirectResponse(target, status.HTTP_302_FOUND)
    res.delete_cookie(COOKIE, path="/api/auth")
    return res


@router.post("/auth/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    if not settings.ALLOW_SIGNUP:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up with a password is turned off here.")
    email = body.email.lower()
    # An invited person already has a row; a password sign-up must never claim it, since it doesn't prove
    # they own the email. They sign in with Google or Microsoft instead.
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = User(email=email, name=body.name, password_hash=hash_password(body.password), last_login_at=utcnow())
    db.add(user)
    db.commit()
    return Token(access_token=create_token(user.id))


@router.post("/auth/login", response_model=Token)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    user.last_login_at = utcnow()
    db.commit()
    return Token(access_token=create_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: MeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    return user
