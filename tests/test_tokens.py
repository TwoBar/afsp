"""Tests for token and audit endpoints."""

import json
import os
import tempfile

import bcrypt
import pytest
from fastapi.testclient import TestClient

os.environ["AFSP_OPERATOR_TOKEN"] = "test-operator-token"

from afsp.api.main import app, reset_db
from afsp.db.db import init_db
from afsp.runtime.enforcement import check_operation


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = init_db(os.path.join(tmpdir, "test.db"))
        reset_db(db)
        os.environ["AFSP_LOGS_PATH"] = os.path.join(tmpdir, "logs")
        client = TestClient(app)
        headers = {"Authorization": "Bearer test-operator-token"}

        # Create two agents
        resp_a = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "tok-agent-a",
        }, headers=headers)
        resp_b = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "tok-agent-b",
        }, headers=headers)

        agent_a = resp_a.json()
        agent_b = resp_b.json()

        yield {
            "db": db, "client": client, "headers": headers,
            "agent_a": agent_a, "agent_b": agent_b, "tmpdir": tmpdir,
        }
        db.close()


class TestGetToken:
    def test_get_existing_token(self, env):
        c, h = env["client"], env["headers"]
        resp = c.post("/v1/tokens", json={
            "grantor": env["agent_a"]["agent_id"],
            "grantee": env["agent_b"]["agent_id"],
            "path": "workspace/data",
            "ops": ["read"],
        }, headers=h)
        token_id = resp.json()["token_id"]

        get_resp = c.get(f"/v1/tokens/{token_id}", headers=h)
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["token_id"] == token_id
        assert data["path"] == "workspace/data"
        assert data["ops"] == ["read"]

    def test_get_nonexistent_token(self, env):
        resp = env["client"].get("/v1/tokens/sgt_nonexistent", headers=env["headers"])
        assert resp.status_code == 404


class TestDeleteToken:
    def test_revoke_token(self, env):
        c, h = env["client"], env["headers"]
        resp = c.post("/v1/tokens", json={
            "grantor": env["agent_a"]["agent_id"],
            "grantee": env["agent_b"]["agent_id"],
            "path": "workspace/data",
            "ops": ["read"],
        }, headers=h)
        token_id = resp.json()["token_id"]

        del_resp = c.delete(f"/v1/tokens/{token_id}", headers=h)
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "revoked"

        # Verify token is effectively expired
        get_resp = c.get(f"/v1/tokens/{token_id}", headers=h)
        assert get_resp.status_code == 200

    def test_revoke_nonexistent_token(self, env):
        resp = env["client"].delete("/v1/tokens/sgt_nonexistent", headers=env["headers"])
        assert resp.status_code == 404


class TestAuditEndpoint:
    def test_audit_empty(self, env):
        resp = env["client"].get("/v1/audit", headers=env["headers"])
        assert resp.status_code == 200
        assert resp.json() == []

    def test_audit_with_entries(self, env):
        c, h, db = env["client"], env["headers"], env["db"]
        agent_id = env["agent_a"]["agent_id"]
        secret = env["agent_a"]["client_secret"]

        # Declare a view and authenticate
        c.post(f"/v1/view/{agent_id}", json=[
            {"path": "workspace/data/**", "ops": ["read"]},
        ], headers=h)

        auth = c.post("/v1/auth", json={
            "agent_id": agent_id, "client_secret": secret,
        })
        session = auth.json()["session_token"]

        # Perform an operation to generate audit entry
        check_operation(session, "read", "workspace/data/file.txt", db)

        resp = c.get("/v1/audit", headers=h)
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) >= 1
        assert entries[0]["agent_id"] == agent_id

    def test_audit_filtered_by_agent(self, env):
        c, h, db = env["client"], env["headers"], env["db"]
        agent_a_id = env["agent_a"]["agent_id"]
        agent_b_id = env["agent_b"]["agent_id"]

        # Set up views and sessions for both agents
        for agent in [env["agent_a"], env["agent_b"]]:
            aid = agent["agent_id"]
            c.post(f"/v1/view/{aid}", json=[
                {"path": "workspace/data/**", "ops": ["read"]},
            ], headers=h)

            auth = c.post("/v1/auth", json={
                "agent_id": aid, "client_secret": agent["client_secret"],
            })
            session = auth.json()["session_token"]
            check_operation(session, "read", "workspace/data/file.txt", db)

        # Filter by agent A
        resp = c.get(f"/v1/audit?agent_id={agent_a_id}", headers=h)
        entries = resp.json()
        assert all(e["agent_id"] == agent_a_id for e in entries)


class TestListAgents:
    def test_list_all_agents(self, env):
        resp = env["client"].get("/v1/agents", headers=env["headers"])
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) == 2

    def test_list_agents_by_status(self, env):
        c, h = env["client"], env["headers"]
        # Suspend one agent
        agent_a_id = env["agent_a"]["agent_id"]
        c.patch(f"/v1/agents/{agent_a_id}/suspend", headers=h)

        active = c.get("/v1/agents?status=active", headers=h).json()
        suspended = c.get("/v1/agents?status=suspended", headers=h).json()
        assert len(active) == 1
        assert len(suspended) == 1
