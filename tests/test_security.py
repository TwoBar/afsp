"""Security tests — path traversal, input validation, auth enforcement."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from afsp.runtime.pathutil import safe_join

os.environ["AFSP_OPERATOR_TOKEN"] = "test-operator-token"

from afsp.api.main import app, reset_db
from afsp.db.db import init_db


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = init_db(os.path.join(tmpdir, "test.db"))
        reset_db(db)
        client = TestClient(app)
        yield {"db": db, "client": client, "tmpdir": tmpdir}
        db.close()


class TestSafeJoin:
    def test_normal_path(self, env):
        root = env["tmpdir"]
        result = safe_join(root, "workspace/finance")
        assert result.endswith("workspace/finance")
        assert result.startswith(os.path.realpath(root))

    def test_rejects_parent_traversal(self, env):
        with pytest.raises(ValueError, match="Path traversal"):
            safe_join(env["tmpdir"], "../../../etc/passwd")

    def test_rejects_dot_dot_in_middle(self, env):
        with pytest.raises(ValueError, match="Path traversal"):
            safe_join(env["tmpdir"], "workspace/../../etc/passwd")

    def test_rejects_null_bytes(self, env):
        with pytest.raises(ValueError, match="null bytes"):
            safe_join(env["tmpdir"], "workspace/\x00evil")

    def test_strips_glob_suffix(self, env):
        root = env["tmpdir"]
        os.makedirs(os.path.join(root, "workspace"), exist_ok=True)
        result = safe_join(root, "workspace/**")
        assert result == os.path.realpath(os.path.join(root, "workspace"))

    def test_root_itself_is_allowed(self, env):
        root = env["tmpdir"]
        result = safe_join(root, "")
        assert result == os.path.realpath(root)


class TestViewEndpointAuth:
    def test_get_view_requires_operator_token(self, env):
        """GET /v1/view/{agent_id} should require authentication."""
        resp = env["client"].get("/v1/view/any-agent-id")
        assert resp.status_code in (401, 422)

    def test_get_view_with_token_succeeds(self, env):
        db = env["db"]
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("sec-agent", "org-1", "sectest"),
        )
        db.commit()

        headers = {"Authorization": "Bearer test-operator-token"}
        resp = env["client"].get("/v1/view/sec-agent", headers=headers)
        assert resp.status_code == 200


class TestInputValidation:
    def test_token_rejects_path_with_dotdot(self, env):
        db = env["db"]
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("val-agent-1", "org-1", "val1"),
        )
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("val-agent-2", "org-1", "val2"),
        )
        db.commit()

        headers = {"Authorization": "Bearer test-operator-token"}
        resp = env["client"].post("/v1/tokens", json={
            "grantor": "val-agent-1",
            "grantee": "val-agent-2",
            "path": "../../etc/passwd",
            "ops": ["read"],
        }, headers=headers)
        assert resp.status_code == 422

    def test_token_rejects_invalid_ops(self, env):
        db = env["db"]
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("val-agent-3", "org-1", "val3"),
        )
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("val-agent-4", "org-1", "val4"),
        )
        db.commit()

        headers = {"Authorization": "Bearer test-operator-token"}
        resp = env["client"].post("/v1/tokens", json={
            "grantor": "val-agent-3",
            "grantee": "val-agent-4",
            "path": "workspace/data",
            "ops": ["delete"],
        }, headers=headers)
        assert resp.status_code == 422

    def test_view_rejects_path_with_dotdot(self, env):
        db = env["db"]
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("val-agent-5", "org-1", "val5"),
        )
        db.commit()

        headers = {"Authorization": "Bearer test-operator-token"}
        resp = env["client"].post("/v1/view/val-agent-5", json=[
            {"path": "../../etc/shadow", "ops": ["read"]},
        ], headers=headers)
        assert resp.status_code == 422

    def test_token_rejects_excessive_ttl(self, env):
        db = env["db"]
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("val-agent-6", "org-1", "val6"),
        )
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("val-agent-7", "org-1", "val7"),
        )
        db.commit()

        headers = {"Authorization": "Bearer test-operator-token"}
        resp = env["client"].post("/v1/tokens", json={
            "grantor": "val-agent-6",
            "grantee": "val-agent-7",
            "path": "workspace/data",
            "ops": ["read"],
            "ttl": 999999,
        }, headers=headers)
        assert resp.status_code == 422
