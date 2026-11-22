import os
import tempfile

# Set before the app is imported: tests get their own SQLite file and never touch backend/.env's database,
# and empty AI keys (which .env can't override) mean no test ever calls a real AI.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["SECRET_KEY"] = "test-secret-that-is-at-least-32-characters-long"
os.environ["ALLOW_SIGNUP"] = "true"
os.environ["GROQ_API_KEY"] = ""
os.environ["DEEPSEEK_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(client):
    """Sign up a password user and return their auth headers."""

    def make(email: str, name: str = "Ana Silva") -> dict:
        res = client.post("/api/auth/signup", json={"name": name, "email": email, "password": "correct-horse"})
        assert res.status_code == 201, res.text
        return {"Authorization": f"Bearer {res.json()['access_token']}"}

    return make
