"""View declaration endpoints."""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from afsp.api.main import get_db, require_operator

router = APIRouter()


class ViewEntry(BaseModel):
    path: str
    ops: list[str]
    flags: Optional[list[str]] = None


class ViewEntryResponse(BaseModel):
    id: str
    path: str
    ops: list[str]
    flags: Optional[list[str]] = None
    source: str = "static"
    expires_at: Optional[str] = None


@router.post("/v1/view/{agent_id}", dependencies=[Depends(require_operator)])
def declare_view(agent_id: str, entries: list[ViewEntry]):
    db = get_db()
    agent = db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Replace entire view
    db.execute("DELETE FROM views WHERE agent_id = ?", (agent_id,))
    for entry in entries:
        vid = f"v_{uuid.uuid4().hex[:8]}"
        db.execute(
            "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
            (vid, agent_id, entry.path, json.dumps(entry.ops), json.dumps(entry.flags or [])),
        )
    db.commit()
    return {"status": "ok", "count": len(entries)}


@router.get("/v1/view/{agent_id}", response_model=list[ViewEntryResponse])
def get_view(agent_id: str):
    """Get the full view for an agent: static views + active SGTs."""
    db = get_db()
    agent = db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    result = []

    # Static views
    rows = db.execute("SELECT * FROM views WHERE agent_id = ?", (agent_id,)).fetchall()
    for row in rows:
        result.append(ViewEntryResponse(
            id=row["id"],
            path=row["path"],
            ops=json.loads(row["ops"]),
            flags=json.loads(row["flags"]) if row["flags"] else None,
            source="static",
        ))

    # Active SGTs
    now = datetime.now(timezone.utc).isoformat()
    sgt_rows = db.execute(
        "SELECT * FROM tokens WHERE grantee = ? AND expires_at > ? AND (single_use = 0 OR used = 0)",
        (agent_id, now),
    ).fetchall()
    for row in sgt_rows:
        result.append(ViewEntryResponse(
            id=row["token_id"],
            path=row["path"],
            ops=json.loads(row["ops"]),
            source="sgt",
            expires_at=row["expires_at"],
        ))

    return result


@router.patch("/v1/view/{agent_id}", dependencies=[Depends(require_operator)])
def add_to_view(agent_id: str, entry: ViewEntry):
    db = get_db()
    agent = db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    vid = f"v_{uuid.uuid4().hex[:8]}"
    db.execute(
        "INSERT INTO views (id, agent_id, path, ops, flags) VALUES (?, ?, ?, ?, ?)",
        (vid, agent_id, entry.path, json.dumps(entry.ops), json.dumps(entry.flags or [])),
    )
    db.commit()
    return {"status": "ok", "id": vid}


@router.delete("/v1/view/{agent_id}/{path_id}", dependencies=[Depends(require_operator)])
def remove_from_view(agent_id: str, path_id: str):
    db = get_db()
    row = db.execute(
        "SELECT id FROM views WHERE id = ? AND agent_id = ?", (path_id, agent_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="View entry not found")
    db.execute("DELETE FROM views WHERE id = ?", (path_id,))
    db.commit()
    return {"status": "removed"}
