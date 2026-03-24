"""Enforcement layer — validates operations against agent views and logs audit entries."""

import fnmatch
import json
import os
import uuid
from datetime import datetime, timezone

from afsp.runtime.projection import get_full_view


def _get_logs_path() -> str:
    return os.environ.get("AFSP_LOGS_PATH", "/var/afsp/logs")


def resolve_session(session_id: str, db) -> str | None:
    """Resolve a session ID to an agent ID. Returns None if invalid/expired/revoked."""
    now = datetime.now(timezone.utc).isoformat()
    row = db.execute(
        "SELECT agent_id FROM sessions WHERE session_id = ? AND expires_at > ? AND revoked = 0",
        (session_id, now),
    ).fetchone()
    return row["agent_id"] if row else None


def matches_glob(path: str, pattern: str) -> bool:
    """Check if a path matches a glob pattern."""
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatch(path, pattern)


def log_audit(agent_id: str | None, op: str, path: str, outcome: str,
              session_id: str | None, db, token_id: str | None = None,
              container_id: str | None = None):
    """Write an audit entry to the database and the audit log file."""
    audit_id = f"evt_{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now(timezone.utc).isoformat()

    # For DB foreign key: use agent_id if valid, skip DB insert if no valid agent
    if agent_id:
        db.execute(
            "INSERT INTO audit (audit_id, agent_id, op, path, outcome, session_id, token_id, timestamp, container_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (audit_id, agent_id, op, path, outcome, session_id, token_id, timestamp, container_id),
        )
        db.commit()

    # Always append to flat log file
    log_dir = _get_logs_path()
    os.makedirs(log_dir, exist_ok=True)
    log_entry = json.dumps({
        "audit_id": audit_id,
        "agent_id": agent_id,
        "op": op,
        "path": path,
        "outcome": outcome,
        "session_id": session_id,
        "token_id": token_id,
        "timestamp": timestamp,
        "container_id": container_id,
    })
    try:
        with open(os.path.join(log_dir, "audit.jsonl"), "a") as f:
            f.write(log_entry + "\n")
    except OSError:
        pass  # Best-effort file logging; DB entry already committed

    return audit_id


def check_operation(session_id: str, op: str, path: str, db,
                    container_id: str | None = None) -> bool:
    """Check if an operation is allowed for the given session.

    Returns True if allowed, False otherwise (ENOENT semantics — never EACCES).
    Always writes an audit entry regardless of outcome.
    """
    agent_id = resolve_session(session_id, db)
    if not agent_id:
        log_audit(None, op, path, "denied", session_id, db, container_id=container_id)
        return False

    view = get_full_view(agent_id, db)
    for entry in view:
        if matches_glob(path, entry["path"]):
            if op in entry["ops"]:
                # For single-use SGTs, atomically mark as used
                if entry.get("single_use"):
                    cursor = db.execute(
                        "UPDATE tokens SET used = 1 WHERE token_id = ? AND used = 0",
                        (entry["id"],),
                    )
                    db.commit()
                    if cursor.rowcount == 0:
                        continue  # Already consumed by concurrent request
                log_audit(agent_id, op, path, "allowed", session_id, db, container_id=container_id)
                return True

    log_audit(agent_id, op, path, "denied", session_id, db, container_id=container_id)
    return False
