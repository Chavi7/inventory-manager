"""Shared fixtures for the Inventory Manager test suite.

`app.py` resolves its secret and initialises the database at *import* time, and
`db.py` reads its path from the environment at import time too — so the
environment has to be right before the import below.
"""
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(REPO_ROOT, "app")
# app.py imports sibling modules as top-level (`from db import get_db`), so the
# app directory itself has to be importable.
sys.path.insert(0, APP_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["INVENTORY_DB_PATH"] = os.path.join(
    tempfile.mkdtemp(prefix="inventory-tests-"), "inventory.db")
os.environ["INVENTORY_SECRET_KEY"] = "test-only-secret-value-not-a-deployment-key"

import app as inventory  # noqa: E402
import db as db_module  # noqa: E402

ADMIN_USERNAME = "teacher"
ADMIN_PASSWORD = "teacher-password-123"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A test client backed by a fresh, seeded database and no admin account."""
    monkeypatch.setattr(db_module, "DB_PATH", str(tmp_path / "inventory.db"))
    db_module.init_db()
    inventory.app.config.update(TESTING=True)
    return inventory.app.test_client()


@pytest.fixture()
def admin_client(client):
    """A test client already logged in as the first admin."""
    client.post("/setup", data={
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
        "confirm": ADMIN_PASSWORD,
    }, follow_redirects=False)
    client.post("/login",
                data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
                follow_redirects=False)
    return client


@pytest.fixture()
def db(client):
    """A direct sqlite connection to the same database the client is using."""
    conn = db_module.get_db()
    yield conn
    conn.close()
