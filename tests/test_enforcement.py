"""Tests for the enforcement layer — Step 6."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from afsp.db.db import init_db
from afsp.runtime.enforcement import check_operation, resolve_session, matches_glob, log_audit


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db = init_db(db_path)
        os.environ["AFSP_LOGS_PATH"] = os.path.join(tmpdir, "logs")
        yield {"db": db, "tmpdir": tmpdir}
        db.close()


@pytest.fixture
def active_session(env):
    """Create an agent with a view and an active session."""
    db = env["db"]
    agent_id = "enf-agent-01"
    session_id = "sess_test123"
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(hours=1)).isoformat()

    db.execute(
        "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
        (agent_id, "org-1", "enftest"),
    )
    db.execute(
        "INSERT INTO sessions (session_id, agent_id, issued_at, expires_at) VALUES (?, ?, ?, ?)",
        (session_id, agent_id, now.isoformat(), expires),
    )
    db.execute(
        "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
        ("v1", agent_id, "workspace/finance/**", json.dumps(["read", "write"]), json.dumps([])),
    )
    db.execute(
        "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
        ("v2", agent_id, "assets/brand/**", json.dumps(["read"]), json.dumps([])),
    )
    db.commit()

    return {"agent_id": agent_id, "session_id": session_id}


class TestMatchesGlob:
    def test_double_star_matches_nested(self):
        assert matches_glob("workspace/finance/report.csv", "workspace/finance/**")

    def test_double_star_matches_deep_nested(self):
        assert matches_glob("workspace/finance/q1/report.csv", "workspace/finance/**")

    def test_double_star_no_match(self):
        assert not matches_glob("workspace/hr/file.txt", "workspace/finance/**")

    def test_exact_prefix_match(self):
        assert matches_glob("workspace/finance", "workspace/finance/**")


class TestResolveSession:
    def test_valid_session(self, env, active_session):
        agent_id = resolve_session(active_session["session_id"], env["db"])
        assert agent_id == active_session["agent_id"]

    def test_expired_session(self, env):
        db = env["db"]
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("exp-agent", "org-1", "expired"),
        )
        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO sessions (session_id, agent_id, issued_at, expires_at) VALUES (?, ?, ?, ?)",
            ("sess_expired", "exp-agent", datetime.now(timezone.utc).isoformat(), expired),
        )
        db.commit()

        assert resolve_session("sess_expired", db) is None

    def test_revoked_session(self, env, active_session):
        db = env["db"]
        db.execute(
            "UPDATE sessions SET revoked = 1 WHERE session_id = ?",
            (active_session["session_id"],),
        )
        db.commit()

        assert resolve_session(active_session["session_id"], db) is None

    def test_nonexistent_session(self, env):
        assert resolve_session("sess_nonexistent", env["db"]) is None


class TestCheckOperation:
    def test_allowed_read(self, env, active_session):
        result = check_operation(
            active_session["session_id"], "read",
            "workspace/finance/report.csv", env["db"],
        )
        assert result is True

    def test_allowed_write(self, env, active_session):
        result = check_operation(
            active_session["session_id"], "write",
            "workspace/finance/output.csv", env["db"],
        )
        assert result is True

    def test_denied_out_of_view(self, env, active_session):
        result = check_operation(
            active_session["session_id"], "read",
            "workspace/secret/data.txt", env["db"],
        )
        assert result is False

    def test_denied_wrong_op(self, env, active_session):
        # assets/brand is read-only
        result = check_operation(
            active_session["session_id"], "write",
            "assets/brand/logo.png", env["db"],
        )
        assert result is False

    def test_allowed_read_on_readonly(self, env, active_session):
        result = check_operation(
            active_session["session_id"], "read",
            "assets/brand/logo.png", env["db"],
        )
        assert result is True

    def test_denied_invalid_session(self, env):
        result = check_operation("sess_bogus", "read", "workspace/finance/x.csv", env["db"])
        assert result is False

    def test_denied_revoked_session(self, env, active_session):
        db = env["db"]
        db.execute(
            "UPDATE sessions SET revoked = 1 WHERE session_id = ?",
            (active_session["session_id"],),
        )
        db.commit()

        result = check_operation(
            active_session["session_id"], "read",
            "workspace/finance/report.csv", db,
        )
        assert result is False

    def test_denied_expired_session(self, env):
        db = env["db"]
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("exp-agent", "org-1", "expired"),
        )
        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO sessions (session_id, agent_id, issued_at, expires_at) VALUES (?, ?, ?, ?)",
            ("sess_exp2", "exp-agent", datetime.now(timezone.utc).isoformat(), expired),
        )
        db.commit()

        result = check_operation("sess_exp2", "read", "workspace/finance/x.csv", db)
        assert result is False


class TestAuditLogging:
    def test_allowed_writes_audit_entry(self, env, active_session):
        check_operation(
            active_session["session_id"], "read",
            "workspace/finance/report.csv", env["db"],
        )

        rows = env["db"].execute(
            "SELECT * FROM audit WHERE agent_id = ? AND outcome = 'allowed'",
            (active_session["agent_id"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["op"] == "read"
        assert rows[0]["path"] == "workspace/finance/report.csv"

    def test_denied_writes_audit_entry(self, env, active_session):
        check_operation(
            active_session["session_id"], "read",
            "workspace/secret/data.txt", env["db"],
        )

        rows = env["db"].execute(
            "SELECT * FROM audit WHERE agent_id = ? AND outcome = 'denied'",
            (active_session["agent_id"],),
        ).fetchall()
        assert len(rows) == 1

    def test_audit_log_file_written(self, env, active_session):
        check_operation(
            active_session["session_id"], "read",
            "workspace/finance/report.csv", env["db"],
        )

        log_path = os.path.join(env["tmpdir"], "logs", "audit.jsonl")
        assert os.path.exists(log_path)
        with open(log_path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["outcome"] == "allowed"
