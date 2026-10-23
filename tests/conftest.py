# Shared test setup. pytest loads this file before the tests: it points the app at a
# temporary database, seeds the demo team once per test file, and provides two
# helpers the tests use to sign in and to send the session token.
# Run every test with:  python -m pytest -q

import os
import sys
import tempfile

# Make the project folder importable (app, scripts).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Every test run uses its own database file.
os.environ.setdefault("PROJECUTE_DB", os.path.join(tempfile.mkdtemp(prefix="projecute-test-"), "test.db"))

# Imported after PROJECUTE_DB is set, so the app opens the test database, not the demo one.
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from scripts.seed_demo import seed  # noqa: E402


@pytest.fixture(scope="module")
def demo():
    """A freshly seeded demo group. Returns the seed info dict."""
    return seed()


# An in-process client for the FastAPI app (no real server or network needed).
@pytest.fixture(scope="module")
def client(demo):
    with TestClient(app) as c:
        yield c


# Sign in as a demo user; returns {token, user}.
def login(client, username: str) -> dict:
    res = client.post("/api/login", json={"username": username})
    assert res.status_code == 200, res.text
    return res.json()


# The header that carries the session token on each request.
def auth(token: str) -> dict:
    return {"X-Token": token}
