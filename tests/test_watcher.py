"""Tests for the watcher — Step 4."""

import os
import tempfile
import time

import pytest
import yaml

from afsp.db.db import init_db
from afsp.runtime.watcher import register_agent, start_watcher, AFSPHandler


@pytest.fixture
def tmp_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        agents_path = os.path.join(tmpdir, "agents")
        os.makedirs(agents_path)
        db = init_db(db_path)
        yield {"db": db, "agents_path": agents_path, "tmpdir": tmpdir}
        db.close()


def _write_afsp_yml(agents_path, name, view=None):
    agent_dir = os.path.join(agents_path, name)
    os.makedirs(agent_dir, exist_ok=True)
    config = {
        "name": name,
        "role": "tester",
        "runtime": "python",
        "entrypoint": "main.py",
        "view": view or [
            {"path": f"workspace/{name}/**", "ops": ["read", "write"]},
        ],
    }
    yml_path = os.path.join(agent_dir, "afsp.yml")
    with open(yml_path, "w") as f:
        yaml.dump(config, f)
    return yml_path


class TestRegisterAgent:
    def test_new_agent_created(self, tmp_env):
        yml_path = _write_afsp_yml(tmp_env["agents_path"], "cfo")
        agent_id = register_agent(yml_path, tmp_env["db"])

        assert agent_id.startswith("cfo-")
        row = tmp_env["db"].execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        assert row["name"] == "cfo"
        assert row["role"] == "tester"
        assert row["status"] == "active"

    def test_credentials_stored(self, tmp_env):
        yml_path = _write_afsp_yml(tmp_env["agents_path"], "cfo")
        agent_id = register_agent(yml_path, tmp_env["db"])

        cred = tmp_env["db"].execute(
            "SELECT * FROM credentials WHERE agent_id = ? AND invalidated = 0",
            (agent_id,),
        ).fetchone()
        assert cred is not None
        assert cred["secret_hash"].startswith("$2b$")

    def test_credential_file_written(self, tmp_env):
        yml_path = _write_afsp_yml(tmp_env["agents_path"], "cfo")
        register_agent(yml_path, tmp_env["db"])

        cred_path = os.path.join(tmp_env["agents_path"], "cfo", ".credentials")
        assert os.path.exists(cred_path)

        with open(cred_path) as f:
            content = f.read()
        assert "AFSP_AGENT_ID=" in content
        assert "AFSP_CLIENT_SECRET=sk_afsp_" in content
        assert "AFSP_RUNTIME=" in content

    def test_credential_file_permissions(self, tmp_env):
        yml_path = _write_afsp_yml(tmp_env["agents_path"], "cfo")
        register_agent(yml_path, tmp_env["db"])

        cred_path = os.path.join(tmp_env["agents_path"], "cfo", ".credentials")
        mode = oct(os.stat(cred_path).st_mode & 0o777)
        assert mode == "0o600"

    def test_views_created(self, tmp_env):
        yml_path = _write_afsp_yml(tmp_env["agents_path"], "cfo", view=[
            {"path": "workspace/finance/**", "ops": ["read", "write"]},
            {"path": "assets/brand/**", "ops": ["read"], "flags": ["noexec"]},
        ])
        agent_id = register_agent(yml_path, tmp_env["db"])

        views = tmp_env["db"].execute(
            "SELECT * FROM views WHERE agent_id = ?", (agent_id,)
        ).fetchall()
        assert len(views) == 2

    def test_update_existing_agent(self, tmp_env):
        yml_path = _write_afsp_yml(tmp_env["agents_path"], "cfo", view=[
            {"path": "workspace/old/**", "ops": ["read"]},
        ])
        agent_id = register_agent(yml_path, tmp_env["db"])

        # Update yml
        yml_path = _write_afsp_yml(tmp_env["agents_path"], "cfo", view=[
            {"path": "workspace/new/**", "ops": ["read", "write"]},
        ])
        agent_id2 = register_agent(yml_path, tmp_env["db"])

        # Same agent
        assert agent_id == agent_id2

        # Views updated
        views = tmp_env["db"].execute(
            "SELECT * FROM views WHERE agent_id = ?", (agent_id,)
        ).fetchall()
        assert len(views) == 1
        assert views[0]["path"] == "workspace/new/**"


class TestWatcherIntegration:
    def test_watcher_detects_new_yml(self, tmp_env):
        observer, handler = start_watcher(tmp_env["agents_path"], tmp_env["db"])
        try:
            _write_afsp_yml(tmp_env["agents_path"], "watcher-test")

            # Poll until watcher processes the file (up to 5s)
            deadline = time.time() + 5.0
            row = None
            while time.time() < deadline:
                row = tmp_env["db"].execute(
                    "SELECT * FROM agents WHERE name = ?", ("watcher-test",)
                ).fetchone()
                if row is not None:
                    break
                time.sleep(0.1)

            assert row is not None
            assert row["status"] == "active"
        finally:
            observer.stop()
            observer.join(timeout=5)
