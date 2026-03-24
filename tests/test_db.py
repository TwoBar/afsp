"""Tests for database foundation — Step 1."""

import json
import tempfile
import uuid
from datetime import datetime, timedelta

import pytest

from afsp.db.db import init_db


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = init_db(f.name)
        yield conn
        conn.close()


class TestAgentsTable:
    def test_insert_and_read(self, db):
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name, role, status) VALUES (?, ?, ?, ?, ?)",
            ("agent-01", "org-1", "cfo", "finance", "active"),
        )
        db.commit()
        row = db.execute("SELECT * FROM agents WHERE agent_id = ?", ("agent-01",)).fetchone()
        assert row["agent_id"] == "agent-01"
        assert row["org_id"] == "org-1"
        assert row["name"] == "cfo"
        assert row["role"] == "finance"
        assert row["status"] == "active"
        assert row["created_at"] is not None

    def test_default_status(self, db):
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("agent-02", "org-1", "cmo"),
        )
        db.commit()
        row = db.execute("SELECT status FROM agents WHERE agent_id = ?", ("agent-02",)).fetchone()
        assert row["status"] == "active"

    def test_primary_key_unique(self, db):
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("agent-01", "org-1", "cfo"),
        )
        db.commit()
        with pytest.raises(Exception):
            db.execute(
                "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
                ("agent-01", "org-1", "duplicate"),
            )


class TestCredentialsTable:
    def test_insert_and_read(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute(
            "INSERT INTO credentials (agent_id, secret_hash, invalidated) VALUES (?, ?, ?)",
            ("a1", "$2b$12$fakehash", 0),
        )
        db.commit()
        row = db.execute("SELECT * FROM credentials WHERE agent_id = ?", ("a1",)).fetchone()
        assert row["secret_hash"] == "$2b$12$fakehash"
        assert row["invalidated"] == 0

    def test_invalidation(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute(
            "INSERT INTO credentials (agent_id, secret_hash) VALUES (?, ?)",
            ("a1", "$2b$12$fakehash"),
        )
        db.commit()
        db.execute("UPDATE credentials SET invalidated = 1 WHERE agent_id = ?", ("a1",))
        db.commit()
        row = db.execute(
            "SELECT * FROM credentials WHERE agent_id = ? AND invalidated = 0", ("a1",)
        ).fetchone()
        assert row is None


class TestSessionsTable:
    def test_insert_and_read(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        sid = str(uuid.uuid4())
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO sessions (session_id, agent_id, expires_at) VALUES (?, ?, ?)",
            (sid, "a1", expires),
        )
        db.commit()
        row = db.execute("SELECT * FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        assert row["agent_id"] == "a1"
        assert row["revoked"] == 0

    def test_revoke_session(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        sid = str(uuid.uuid4())
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO sessions (session_id, agent_id, expires_at) VALUES (?, ?, ?)",
            (sid, "a1", expires),
        )
        db.commit()
        db.execute("UPDATE sessions SET revoked = 1 WHERE session_id = ?", (sid,))
        db.commit()
        row = db.execute(
            "SELECT * FROM sessions WHERE session_id = ? AND revoked = 0", (sid,)
        ).fetchone()
        assert row is None


class TestViewsTable:
    def test_insert_and_read(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        ops = json.dumps(["read", "write"])
        flags = json.dumps(["write_once"])
        db.execute(
            "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
            ("v1", "a1", "workspace/finance/**", ops, flags),
        )
        db.commit()
        row = db.execute("SELECT * FROM views WHERE id = ?", ("v1",)).fetchone()
        assert row["path"] == "workspace/finance/**"
        assert json.loads(row["ops"]) == ["read", "write"]
        assert json.loads(row["flags"]) == ["write_once"]


class TestRoleTemplatesTable:
    def test_insert_and_read(self, db):
        ops = json.dumps(["read"])
        db.execute(
            "INSERT INTO role_templates (role, path, ops) VALUES (?, ?, ?)",
            ("finance", "workspace/finance/**", ops),
        )
        db.commit()
        rows = db.execute("SELECT * FROM role_templates WHERE role = ?", ("finance",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["path"] == "workspace/finance/**"


class TestTokensTable:
    def test_insert_and_read(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a2", "o1", "n2"))
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        ops = json.dumps(["read"])
        db.execute(
            "INSERT INTO tokens (token_id, grantor, grantee, path, ops, expires_at, single_use, issued_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("sgt-1", "a1", "a2", "workspace/handoffs/inbound/file.txt", ops, expires, 1, "operator"),
        )
        db.commit()
        row = db.execute("SELECT * FROM tokens WHERE token_id = ?", ("sgt-1",)).fetchone()
        assert row["grantor"] == "a1"
        assert row["grantee"] == "a2"
        assert row["single_use"] == 1
        assert row["used"] == 0

    def test_mark_used(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a2", "o1", "n2"))
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        ops = json.dumps(["read"])
        db.execute(
            "INSERT INTO tokens (token_id, grantor, grantee, path, ops, expires_at, issued_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sgt-1", "a1", "a2", "workspace/file.txt", ops, expires, "operator"),
        )
        db.commit()
        db.execute("UPDATE tokens SET used = 1 WHERE token_id = ?", ("sgt-1",))
        db.commit()
        row = db.execute("SELECT used FROM tokens WHERE token_id = ?", ("sgt-1",)).fetchone()
        assert row["used"] == 1


class TestFederatedTrustTable:
    def test_insert_and_read(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute(
            "INSERT INTO federated_trust (agent_id, provider, provider_subject, org_id) "
            "VALUES (?, ?, ?, ?)",
            ("a1", "google", "sub-123", "o1"),
        )
        db.commit()
        row = db.execute("SELECT * FROM federated_trust WHERE agent_id = ?", ("a1",)).fetchone()
        assert row["provider"] == "google"
        assert row["provider_subject"] == "sub-123"


class TestAuditTable:
    def test_insert_and_read(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute(
            "INSERT INTO audit (audit_id, agent_id, op, path, outcome) VALUES (?, ?, ?, ?, ?)",
            ("evt-1", "a1", "read", "workspace/finance/report.csv", "allowed"),
        )
        db.commit()
        row = db.execute("SELECT * FROM audit WHERE audit_id = ?", ("evt-1",)).fetchone()
        assert row["op"] == "read"
        assert row["outcome"] == "allowed"
        assert row["timestamp"] is not None

    def test_denied_outcome(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute(
            "INSERT INTO audit (audit_id, agent_id, op, path, outcome) VALUES (?, ?, ?, ?, ?)",
            ("evt-2", "a1", "write", "workspace/secret/data.txt", "denied"),
        )
        db.commit()
        row = db.execute("SELECT * FROM audit WHERE audit_id = ?", ("evt-2",)).fetchone()
        assert row["outcome"] == "denied"

    def test_filter_by_agent(self, db):
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a1", "o1", "n1"))
        db.execute("INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)", ("a2", "o1", "n2"))
        db.execute(
            "INSERT INTO audit (audit_id, agent_id, op, path, outcome) VALUES (?, ?, ?, ?, ?)",
            ("evt-1", "a1", "read", "p1", "allowed"),
        )
        db.execute(
            "INSERT INTO audit (audit_id, agent_id, op, path, outcome) VALUES (?, ?, ?, ?, ?)",
            ("evt-2", "a2", "read", "p2", "allowed"),
        )
        db.commit()
        rows = db.execute("SELECT * FROM audit WHERE agent_id = ?", ("a1",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["audit_id"] == "evt-1"
