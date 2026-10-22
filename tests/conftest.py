import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Every test run uses its own database file.
os.environ.setdefault("PROJECUTE_DB", os.path.join(tempfile.mkdtemp(prefix="projecute-test-"), "test.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from scripts.seed_demo import seed  # noqa: E402


@pytest.fixture(scope="module")
def demo():
    """A freshly seeded demo group. Returns the seed info dict."""
    return seed()


@pytest.fixture(scope="module")
def client(demo):
    with TestClient(app) as c:
        yield c


def login(client, username: str) -> dict:
    res = client.post("/api/login", json={"username": username})
    assert res.status_code == 200, res.text
    return res.json()


def auth(token: str) -> dict:
    return {"X-Token": token}
