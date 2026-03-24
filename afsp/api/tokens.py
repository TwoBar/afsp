"""SGT (Scope Grant Token) operations."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from afsp.api.main import get_db, require_operator
from afsp.db import safe_json_loads

router = APIRouter()


class TokenRequest(BaseModel):
    grantor: str
    grantee: str
    path: str
    ops: list[str]
    ttl: int = 3600
    single_use: bool = False
    issued_by: str = "operator"

    @field_validator("path")
    @classmethod
    def validate_path(cls, v):
        if "\x00" in v:
            raise ValueError("Path contains null bytes")
        if ".." in v.split("/"):
            raise ValueError("Path contains '..' components")
        return v

    @field_validator("ops")
    @classmethod
    def validate_ops(cls, v):
        allowed = {"read", "write", "execute"}
        for op in v:
            if op not in allowed:
                raise ValueError(f"Invalid op: {op}. Allowed: {allowed}")
        return v

    @field_validator("ttl")
    @classmethod
    def validate_ttl(cls, v):
        if v < 1 or v > 86400:
            raise ValueError("TTL must be 1–86400 seconds")
        return v


class TokenResponse(BaseModel):
    token_id: str
    grantor: str
    grantee: str
    path: str
    ops: list[str]
    expires_at: str
    single_use: bool


@router.post("/v1/tokens", response_model=TokenResponse, dependencies=[Depends(require_operator)])
def issue_token(req: TokenRequest):
    db = get_db()

    # Verify both agents exist
    for aid in [req.grantor, req.grantee]:
        agent = db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (aid,)).fetchone()
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent {aid} not found")

    token_id = f"sgt_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=req.ttl)

    db.execute(
        "INSERT INTO tokens (token_id, grantor, grantee, path, ops, expires_at, single_use, issued_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (token_id, req.grantor, req.grantee, req.path, json.dumps(req.ops),
         expires_at.isoformat(), 1 if req.single_use else 0, req.issued_by),
    )
    db.commit()

    return TokenResponse(
        token_id=token_id,
        grantor=req.grantor,
        grantee=req.grantee,
        path=req.path,
        ops=req.ops,
        expires_at=expires_at.isoformat(),
        single_use=req.single_use,
    )


@router.get("/v1/tokens/{token_id}", dependencies=[Depends(require_operator)])
def get_token(token_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM tokens WHERE token_id = ?", (token_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")
    return {
        "token_id": row["token_id"],
        "grantor": row["grantor"],
        "grantee": row["grantee"],
        "path": row["path"],
        "ops": safe_json_loads(row["ops"]),
        "expires_at": row["expires_at"],
        "single_use": bool(row["single_use"]),
        "used": bool(row["used"]),
    }


@router.delete("/v1/tokens/{token_id}", dependencies=[Depends(require_operator)])
def revoke_token(token_id: str):
    db = get_db()
    row = db.execute("SELECT token_id FROM tokens WHERE token_id = ?", (token_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")
    # Set expires_at to now to effectively revoke
    db.execute(
        "UPDATE tokens SET expires_at = datetime('now') WHERE token_id = ?", (token_id,)
    )
    db.commit()
    return {"status": "revoked", "token_id": token_id}


@router.get("/v1/audit", dependencies=[Depends(require_operator)])
def query_audit(agent_id: str | None = None):
    db = get_db()
    if agent_id:
        rows = db.execute(
            "SELECT * FROM audit WHERE agent_id = ? ORDER BY timestamp DESC LIMIT 100",
            (agent_id,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM audit ORDER BY timestamp DESC LIMIT 100"
        ).fetchall()

    return [
        {
            "audit_id": r["audit_id"],
            "agent_id": r["agent_id"],
            "op": r["op"],
            "path": r["path"],
            "outcome": r["outcome"],
            "session_id": r["session_id"],
            "token_id": r["token_id"],
            "timestamp": r["timestamp"],
            "container_id": r["container_id"],
        }
        for r in rows
    ]
