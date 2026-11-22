import os
import re
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]

# backend/.env; real environment variables win over it.
load_dotenv(BACKEND_DIR / ".env")


class Settings:
    # psycopg 3 is installed, so every Postgres URL goes to that driver.
    # A bare postgres:// or postgresql:// would make SQLAlchemy look for psycopg2.
    DATABASE_URL: str = re.sub(
        r"^postgres(?:ql)?(?:\+psycopg2)?://",
        "postgresql+psycopg://",
        os.getenv("DATABASE_URL") or f"sqlite:///{(BACKEND_DIR / 'dev.db').as_posix()}",
    )

    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES") or 60 * 24 * 7)

    # Deployed frontend origins, comma-separated. Localhost on any port is always allowed (main.py).
    ALLOWED_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

    # Password sign-up doesn't prove email ownership, and invites match people by email,
    # so it stays off unless a dev or demo setup turns it on.
    ALLOW_SIGNUP: bool = os.getenv("ALLOW_SIGNUP", "").lower() == "true"

    # AI: DeepSeek first when its key is set, then Groq. Groq retires models, so the name comes from env.
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    AI_MODEL: str = os.getenv("AI_MODEL") or "openai/gpt-oss-120b"
    AI_TEMPERATURE: float = float(os.getenv("AI_TEMPERATURE") or 0.3)
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL") or "whisper-large-v3-turbo"  # Groq speech to text

    # Sign-in and calendars. A provider shows up on the sign-in page only when both of its values are set.
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    MICROSOFT_CLIENT_ID: str = os.getenv("MICROSOFT_CLIENT_ID", "")
    MICROSOFT_CLIENT_SECRET: str = os.getenv("MICROSOFT_CLIENT_SECRET", "")
    # Where this API and the web app are reached from a browser: the OAuth redirect URIs are built from API_URL.
    API_URL: str = (os.getenv("API_URL") or "http://localhost:8000").rstrip("/")
    FRONTEND_URL: str = (os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")
    # Who may create an account by signing in with Google or Microsoft without being invited: emails and/or
    # @domains, comma-separated, or * for anyone. Empty: invite-only. Invited people can always sign in.
    NEW_ACCOUNT_EMAILS: list[str] = [e.strip().lower() for e in os.getenv("NEW_ACCOUNT_EMAILS", "").split(",") if e.strip()]
    # Fernet key for stored calendar tokens. Unset: derived from SECRET_KEY, so changing that disconnects calendars.
    TOKEN_KEY: str = os.getenv("TOKEN_KEY", "")

    def __init__(self):
        # Login tokens are signed with this; a known value would let anyone forge one.
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY == "replace-with-a-long-random-secret":
            raise ValueError(
                "SECRET_KEY must be set to a private random value of 32+ characters, e.g. the output of: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )


settings = Settings()
