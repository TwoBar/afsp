"""Watches /var/afsp/agents/ for afsp.yml files and registers agents."""

import json
import os
import secrets
import uuid

import bcrypt
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from afsp.db.db import init_db

AGENTS_PATH = os.environ.get("AFSP_AGENTS_PATH", "/var/afsp/agents")


def generate_client_secret() -> str:
    return f"sk_afsp_{secrets.token_hex(16)}"


def parse_afsp_yml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def register_agent(yml_path: str, db):
    """Register or update an agent from an afsp.yml file."""
    config = parse_afsp_yml(yml_path)
    agent_dir = os.path.dirname(yml_path)
    name = config["name"]

    # Check if agent already exists by name
    existing = db.execute(
        "SELECT agent_id FROM agents WHERE name = ?", (name,)
    ).fetchone()

    if existing:
        agent_id = existing["agent_id"]
        _update_views(agent_id, config.get("view", []), db)
    else:
        agent_id = f"{name}-{uuid.uuid4().hex[:4]}"
        org_id = config.get("org_id", "default")
        role = config.get("role")

        db.execute(
            "INSERT INTO agents (agent_id, org_id, name, role) VALUES (?, ?, ?, ?)",
            (agent_id, org_id, name, role),
        )

        # Generate and store credential
        client_secret = generate_client_secret()
        secret_hash = bcrypt.hashpw(
            client_secret.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        db.execute(
            "INSERT INTO credentials (agent_id, secret_hash) VALUES (?, ?)",
            (agent_id, secret_hash),
        )

        # Set up views
        _update_views(agent_id, config.get("view", []), db)
        db.commit()

        # Write credential file
        _write_credentials(agent_dir, agent_id, client_secret, config)

    return agent_id


def _update_views(agent_id: str, view_entries: list, db):
    """Replace all view entries for an agent."""
    db.execute("DELETE FROM views WHERE agent_id = ?", (agent_id,))
    for entry in view_entries:
        vid = f"v_{uuid.uuid4().hex[:8]}"
        ops = json.dumps(entry.get("ops", []))
        flags = json.dumps(entry.get("flags", []))
        db.execute(
            "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
            (vid, agent_id, entry["path"], ops, flags),
        )
    db.commit()


def _write_credentials(agent_dir: str, agent_id: str, client_secret: str, config: dict):
    """Write .credentials file to the agent directory."""
    runtime_url = os.environ.get("AFSP_RUNTIME_URL", "http://localhost:8000")
    cred_path = os.path.join(agent_dir, ".credentials")
    with open(cred_path, "w") as f:
        f.write(f"AFSP_AGENT_ID={agent_id}\n")
        f.write(f"AFSP_CLIENT_SECRET={client_secret}\n")
        f.write(f"AFSP_RUNTIME={runtime_url}\n")
    os.chmod(cred_path, 0o600)


def suspend_agent_by_path(agent_dir: str, db):
    """Suspend an agent whose directory was deleted."""
    dir_name = os.path.basename(agent_dir)
    row = db.execute("SELECT agent_id FROM agents WHERE name = ?", (dir_name,)).fetchone()
    if row:
        db.execute("UPDATE sessions SET revoked = 1 WHERE agent_id = ?", (row["agent_id"],))
        db.execute(
            "UPDATE agents SET status = 'suspended' WHERE agent_id = ?", (row["agent_id"],)
        )
        db.commit()


class AFSPHandler(FileSystemEventHandler):
    def __init__(self, db=None):
        self.db = db or init_db()

    def on_created(self, event):
        if event.src_path.endswith("afsp.yml"):
            register_agent(event.src_path, self.db)

    def on_modified(self, event):
        if event.src_path.endswith("afsp.yml"):
            register_agent(event.src_path, self.db)

    def on_deleted(self, event):
        if event.src_path.endswith("afsp.yml"):
            parent = os.path.dirname(event.src_path)
            suspend_agent_by_path(parent, self.db)


def start_watcher(agents_path: str | None = None, db=None):
    """Start the filesystem watcher. Blocking call."""
    path = agents_path or AGENTS_PATH
    os.makedirs(path, exist_ok=True)
    handler = AFSPHandler(db=db)
    observer = Observer()
    observer.schedule(handler, path, recursive=True)
    observer.start()
    return observer, handler
