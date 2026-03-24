"""End-to-end test — Step 10.

Two agents with overlapping handoff zone. Agent A writes to outbound,
SGT issued to Agent B, Agent B sees the file, Agent A cannot see B's workspace.
Audit log records everything.
"""

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
from afsp.runtime.projection import build_volume_spec


@pytest.fixture
def e2e_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = init_db(db_path)
        reset_db(db)
        os.environ["AFSP_LOGS_PATH"] = os.path.join(tmpdir, "logs")

        client = TestClient(app)
        headers = {"Authorization": "Bearer test-operator-token"}

        yield {"db": db, "client": client, "headers": headers, "tmpdir": tmpdir}
        db.close()


class TestEndToEnd:
    def test_two_agents_handoff_flow(self, e2e_env):
        client = e2e_env["client"]
        headers = e2e_env["headers"]
        db = e2e_env["db"]

        # --- Create Agent A (producer) ---
        resp_a = client.post("/v1/agents", json={
            "org_id": "org-1",
            "name": "agent-a",
            "role": "producer",
        }, headers=headers)
        assert resp_a.status_code == 200
        agent_a = resp_a.json()
        agent_a_id = agent_a["agent_id"]
        secret_a = agent_a["client_secret"]

        # Declare Agent A's view
        client.post(f"/v1/view/{agent_a_id}", json=[
            {"path": "workspace/agent-a/**", "ops": ["read", "write"]},
            {"path": "workspace/handoffs/outbound/**", "ops": ["write"], "flags": ["write_once"]},
        ], headers=headers)

        # --- Create Agent B (consumer) ---
        resp_b = client.post("/v1/agents", json={
            "org_id": "org-1",
            "name": "agent-b",
            "role": "consumer",
        }, headers=headers)
        assert resp_b.status_code == 200
        agent_b = resp_b.json()
        agent_b_id = agent_b["agent_id"]
        secret_b = agent_b["client_secret"]

        # Declare Agent B's view
        client.post(f"/v1/view/{agent_b_id}", json=[
            {"path": "workspace/agent-b/**", "ops": ["read", "write"]},
            {"path": "workspace/handoffs/inbound/**", "ops": ["read"]},
        ], headers=headers)

        # --- Agent A authenticates ---
        auth_a = client.post("/v1/auth", json={
            "agent_id": agent_a_id,
            "client_secret": secret_a,
        })
        assert auth_a.status_code == 200
        session_a = auth_a.json()["session_token"]

        # --- Agent B authenticates ---
        auth_b = client.post("/v1/auth", json={
            "agent_id": agent_b_id,
            "client_secret": secret_b,
        })
        assert auth_b.status_code == 200
        session_b = auth_b.json()["session_token"]

        # --- Agent A writes to outbound (allowed) ---
        assert check_operation(session_a, "write", "workspace/handoffs/outbound/brief.md", db)

        # --- Agent A cannot see Agent B's workspace ---
        assert not check_operation(session_a, "read", "workspace/agent-b/data.csv", db)

        # --- Agent B cannot see outbound (not in view) ---
        assert not check_operation(session_b, "read", "workspace/handoffs/outbound/brief.md", db)

        # --- Issue SGT: grant Agent B read access to handoff file ---
        sgt_resp = client.post("/v1/tokens", json={
            "grantor": agent_a_id,
            "grantee": agent_b_id,
            "path": "workspace/handoffs/outbound/brief.md",
            "ops": ["read"],
            "ttl": 3600,
        }, headers=headers)
        assert sgt_resp.status_code == 200
        sgt = sgt_resp.json()

        # --- Agent B's view now includes the SGT ---
        view_b = client.get(f"/v1/view/{agent_b_id}", headers=headers).json()
        sources = {v["source"] for v in view_b}
        assert "sgt" in sources

        # --- Agent B can now read the handoff file via SGT ---
        assert check_operation(session_b, "read", "workspace/handoffs/outbound/brief.md", db)

        # --- Agent B still cannot write to outbound ---
        assert not check_operation(session_b, "write", "workspace/handoffs/outbound/brief.md", db)

        # --- Agent A cannot see Agent B's private workspace ---
        assert not check_operation(session_a, "read", "workspace/agent-b/private.txt", db)

        # --- Verify audit log records both agents' operations ---
        audit_a = db.execute(
            "SELECT * FROM audit WHERE agent_id = ?", (agent_a_id,)
        ).fetchall()
        audit_b = db.execute(
            "SELECT * FROM audit WHERE agent_id = ?", (agent_b_id,)
        ).fetchall()

        # Agent A: 1 allowed write + 2 denied reads = 3
        assert len(audit_a) == 3
        # Agent B: 2 denied (outbound read + outbound write) + 1 allowed (SGT read) = 3
        assert len(audit_b) == 3

        # Verify both allowed and denied outcomes exist
        outcomes_a = {r["outcome"] for r in audit_a}
        outcomes_b = {r["outcome"] for r in audit_b}
        assert "allowed" in outcomes_a
        assert "denied" in outcomes_a
        assert "allowed" in outcomes_b
        assert "denied" in outcomes_b

    def test_projection_produces_correct_mounts(self, e2e_env):
        client = e2e_env["client"]
        headers = e2e_env["headers"]
        db = e2e_env["db"]

        resp = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "proj-e2e",
        }, headers=headers)
        agent_id = resp.json()["agent_id"]

        client.post(f"/v1/view/{agent_id}", json=[
            {"path": "workspace/data/**", "ops": ["read", "write"]},
            {"path": "assets/shared/**", "ops": ["read"]},
        ], headers=headers)

        vols = build_volume_spec(agent_id, db, "/var/afsp/volumes")
        assert len(vols) == 2

        data_vol = [v for v in vols if "data" in v["container_path"]][0]
        assert data_vol["mode"] == "rw"
        assert data_vol["noexec"] is True
        assert data_vol["nosuid"] is True

        shared_vol = [v for v in vols if "shared" in v["container_path"]][0]
        assert shared_vol["mode"] == "ro"

    def test_suspension_revokes_all_access(self, e2e_env):
        client = e2e_env["client"]
        headers = e2e_env["headers"]
        db = e2e_env["db"]

        resp = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "sus-e2e",
        }, headers=headers)
        agent_id = resp.json()["agent_id"]
        secret = resp.json()["client_secret"]

        client.post(f"/v1/view/{agent_id}", json=[
            {"path": "workspace/data/**", "ops": ["read"]},
        ], headers=headers)

        auth = client.post("/v1/auth", json={
            "agent_id": agent_id, "client_secret": secret,
        })
        session = auth.json()["session_token"]

        # Can read before suspension
        assert check_operation(session, "read", "workspace/data/file.txt", db)

        # Suspend
        client.patch(f"/v1/agents/{agent_id}/suspend", headers=headers)

        # Cannot read after suspension
        assert not check_operation(session, "read", "workspace/data/file.txt", db)

        # Cannot re-authenticate (suspended)
        reauth = client.post("/v1/auth", json={
            "agent_id": agent_id, "client_secret": "anything",
        })
        assert reauth.status_code == 401
