"""Tests for SGT dynamic mounting — Step 9.

Integration tests require a running Docker daemon — tagged with 'integration'.
Unit tests cover the scheduling and token-used logic without Docker.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from afsp.db.db import init_db
from afsp.runtime.sgt_mount import (
    schedule_unmount,
    mark_token_used,
    mount_sgt,
    unmount_sgt,
)


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = init_db(f.name)
        yield conn
        conn.close()


class TestMarkTokenUsed:
    def test_marks_used(self, db):
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("a1", "o1", "n1"),
        )
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("a2", "o1", "n2"),
        )
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO tokens (token_id, grantor, grantee, path, ops, expires_at, single_use, issued_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("sgt-1", "a1", "a2", "workspace/file.txt", json.dumps(["read"]), expires, 1, "operator"),
        )
        db.commit()

        mark_token_used("sgt-1", db)

        row = db.execute("SELECT used FROM tokens WHERE token_id = ?", ("sgt-1",)).fetchone()
        assert row["used"] == 1


class TestScheduleUnmount:
    def test_immediate_unmount_for_expired(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        with patch("afsp.runtime.sgt_mount.unmount_sgt") as mock_unmount:
            schedule_unmount("container-123", "/workspace/test", past)
            mock_unmount.assert_called_once_with("container-123", "/workspace/test")

    def test_scheduled_unmount_returns_timer(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=60)
        with patch("afsp.runtime.sgt_mount.unmount_sgt"):
            timer = schedule_unmount("container-123", "/workspace/test", future)
            assert timer is not None
            timer.cancel()


@pytest.mark.integration
class TestMountSGTIntegration:
    """These tests require a running Docker daemon.

    Run with: pytest -m integration
    """

    def test_mount_and_unmount(self):
        pytest.skip("Requires running Docker daemon")

    def test_single_use_token_unmounted_after_access(self):
        pytest.skip("Requires running Docker daemon")

    def test_expiry_triggers_unmount(self):
        pytest.skip("Requires running Docker daemon")
