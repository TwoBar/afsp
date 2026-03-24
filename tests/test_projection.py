"""Tests for the projection layer — Step 5."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from afsp.db.db import init_db
from afsp.runtime.projection import build_volume_spec, get_full_view


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        conn = init_db(f.name)
        yield conn
        conn.close()


@pytest.fixture
def agent_with_view(db):
    """Create an agent with a static view."""
    agent_id = "proj-agent-01"
    db.execute(
        "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
        (agent_id, "org-1", "projtest"),
    )
    db.execute(
        "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
        ("v1", agent_id, "workspace/finance/**", json.dumps(["read", "write"]), json.dumps(["write_once"])),
    )
    db.execute(
        "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
        ("v2", agent_id, "assets/brand/**", json.dumps(["read"]), json.dumps([])),
    )
    db.commit()
    return agent_id


class TestBuildVolumeSpec:
    def test_basic_volume_spec(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        assert len(vols) == 2

    def test_writable_mount_has_rw_mode(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        finance_vol = [v for v in vols if "finance" in v["container_path"]][0]
        assert finance_vol["mode"] == "rw"

    def test_readonly_mount_has_ro_mode(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        brand_vol = [v for v in vols if "brand" in v["container_path"]][0]
        assert brand_vol["mode"] == "ro"

    def test_writable_mounts_carry_noexec(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        finance_vol = [v for v in vols if "finance" in v["container_path"]][0]
        assert finance_vol["noexec"] is True

    def test_readonly_without_noexec_flag(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        brand_vol = [v for v in vols if "brand" in v["container_path"]][0]
        assert brand_vol["noexec"] is False

    def test_all_mounts_carry_nosuid(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        for vol in vols:
            assert vol["nosuid"] is True

    def test_container_paths_prefixed(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        for vol in vols:
            assert vol["container_path"].startswith("/workspace/")

    def test_host_paths_resolve_correctly(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        finance_vol = [v for v in vols if "finance" in v["container_path"]][0]
        assert finance_vol["host_path"] == "/var/afsp/volumes/workspace/finance"

    def test_sgt_paths_included(self, db, agent_with_view):
        # Create grantor agent
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("grantor-01", "org-1", "grantor"),
        )
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        db.execute(
            "INSERT INTO tokens (token_id, grantor, grantee, path, ops, expires_at, issued_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sgt-1", "grantor-01", agent_with_view, "workspace/handoffs/file.txt",
             json.dumps(["read"]), expires, "operator"),
        )
        db.commit()

        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        assert len(vols) == 3
        sgt_vol = [v for v in vols if "handoffs" in v["container_path"]][0]
        assert sgt_vol["mode"] == "ro"

    def test_out_of_view_paths_absent(self, db, agent_with_view):
        vols = build_volume_spec(agent_with_view, db, "/var/afsp/volumes")
        paths = [v["container_path"] for v in vols]
        assert not any("secret" in p for p in paths)
        assert not any("other-agent" in p for p in paths)

    def test_empty_view_returns_no_volumes(self, db):
        db.execute(
            "INSERT INTO agents (agent_id, org_id, name) VALUES (?, ?, ?)",
            ("empty-agent", "org-1", "empty"),
        )
        db.commit()
        vols = build_volume_spec("empty-agent", db, "/var/afsp/volumes")
        assert vols == []
