"""Shared test fixtures."""

import os
import tempfile

import bcrypt
import pytest
from fastapi.testclient import TestClient

# Set operator token before importing the app
os.environ["AFSP_OPERATOR_TOKEN"] = "test-operator-token"

from afsp.api.main import app, reset_db
from afsp.db.db import init_db


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = init_db(f.name)
        yield conn
        conn.close()


@pytest.fixture
def client(db):
    reset_db(db)
    return TestClient(app)


@pytest.fixture
def operator_headers():
    return {"Authorization": "Bearer test-operator-token"}


@pytest.fixture
def seeded_agent(db):
    """Create an agent with a known client secret for auth tests."""
    agent_id = "test-agent-01"
    client_secret = "sk_afsp_testsecret123"
    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    db.execute(
        "INSERT INTO agents (agent_id, org_id, name, role, status) VALUES (?, ?, ?, ?, ?)",
        (agent_id, "org-test", "test-agent", "tester", "active"),
    )
    db.execute(
        "INSERT INTO credentials (agent_id, secret_hash, invalidated) VALUES (?, ?, ?)",
        (agent_id, secret_hash, 0),
    )
    db.commit()

    return {"agent_id": agent_id, "client_secret": client_secret}
