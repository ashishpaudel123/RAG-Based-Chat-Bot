import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp(prefix="chatbot-test-")
os.environ.update(
    ENVIRONMENT="test",
    # Set TEST_DATABASE_URL to run the suite against PostgreSQL instead of SQLite.
    DATABASE_URL=os.getenv("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db"),
    CHROMA_DIR=f"{_tmp}/chroma",
    STORAGE_DIR=f"{_tmp}/docs",
    LLM_PROVIDER="fake",
    RELEVANCE_THRESHOLD="0.2",
    ADMIN_EMAIL="admin@example.com",
    ADMIN_PASSWORD="Admin12345",
    JWT_SECRET="test-secret-key-that-is-long-enough-for-hs256",
    RATE_LIMIT_CHAT="1000",
    RATE_LIMIT_AUTH="1000",
    RATE_LIMIT_UPLOAD="1000",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.rate_limit import limiter  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()


def auth_headers(client, email="admin@example.com", password="Admin12345"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client):
    return auth_headers(client)


@pytest.fixture(scope="session")
def user_headers(client):
    r = client.post("/api/auth/register",
                    json={"email": "user@example.com", "full_name": "Test User", "password": "Password123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def knowledge(client, admin_headers):
    ids = []
    for path in sorted(SAMPLE_DIR.glob("*.md")):
        r = client.post("/api/documents/upload", headers=admin_headers,
                        files={"file": (path.name, path.read_bytes(), "text/markdown")})
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "indexed", r.json()
        ids.append(r.json()["id"])
    return ids
