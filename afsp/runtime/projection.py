"""Projection layer — translates view declarations into bind mount specifications."""

import json
import os
from datetime import datetime, timezone


VOLUMES_PATH = os.environ.get("AFSP_VOLUMES_PATH", "/var/afsp/volumes")


def get_full_view(agent_id: str, db) -> list[dict]:
    """Get the complete view for an agent: static views + active SGTs."""
    rows = db.execute(
        "SELECT id, path, ops, flags FROM views WHERE agent_id = ?", (agent_id,)
    ).fetchall()

    now = datetime.now(timezone.utc).isoformat()
    sgt_rows = db.execute(
        "SELECT token_id AS id, path, ops, 'null' AS flags FROM tokens "
        "WHERE grantee = ? AND expires_at > ? AND (single_use = 0 OR used = 0)",
        (agent_id, now),
    ).fetchall()

    result = []
    for row in rows:
        result.append({
            "id": row["id"],
            "path": row["path"],
            "ops": json.loads(row["ops"]),
            "flags": json.loads(row["flags"]) if row["flags"] and row["flags"] != "null" else [],
        })
    for row in sgt_rows:
        result.append({
            "id": row["id"],
            "path": row["path"],
            "ops": json.loads(row["ops"]),
            "flags": [],
        })

    return result


def resolve_backing_store(path: str, volumes_path: str | None = None) -> str:
    """Resolve a view path to a host filesystem path."""
    root = volumes_path or VOLUMES_PATH
    return os.path.join(root, path.rstrip("/*"))


def build_volume_spec(agent_id: str, db, volumes_path: str | None = None) -> list[dict]:
    """Build Docker volume mount specifications from an agent's view."""
    view_rows = get_full_view(agent_id, db)
    volumes = []

    for row in view_rows:
        path = row["path"]
        ops = row["ops"]
        flags = row["flags"]

        host_path = resolve_backing_store(path, volumes_path)
        container_path = f"/workspace/{path.rstrip('/*')}"
        mode = "rw" if "write" in ops else "ro"

        volumes.append({
            "host_path": host_path,
            "container_path": container_path,
            "mode": mode,
            "noexec": "noexec" in flags or "write" in ops,
            "nosuid": True,
        })

    return volumes
