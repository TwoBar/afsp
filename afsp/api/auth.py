"""POST /v1/auth — credential exchange for session token."""

import secrets
from datetime import datetime, timedelta, timezone
import os

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from afsp.api.main import get_db

router = APIRouter()

SESSION_TTL = int(os.environ.get("AFSP_SESSION_TTL", "3600"))


class AuthRequest(BaseModel):
    agent_id: str
    client_secret: str


class AuthResponse(BaseModel):
    session_token: str


@router.post("/v1/auth", response_model=AuthResponse)
def auth_exchange(req: AuthRequest):
    db = get_db()

    # Check agent exists and is active
    agent = db.execute(
        "SELECT status FROM agents WHERE agent_id = ?", (req.agent_id,)
    ).fetchone()
    if not agent:
        raise HTTPException(status_code=401, detail="Authentication failed")
    if agent["status"] != "active":
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Look up valid credential
    cred = db.execute(
        "SELECT rowid, secret_hash FROM credentials WHERE agent_id = ? AND invalidated = 0",
        (req.agent_id,),
    ).fetchone()
    if not cred:
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Verify bcrypt hash
    if not bcrypt.checkpw(
        req.client_secret.encode("utf-8"), cred["secret_hash"].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Invalidate the credential (single-use)
    db.execute(
        "UPDATE credentials SET invalidated = 1 WHERE rowid = ?", (cred["rowid"],)
    )

    # Create session
    session_id = f"sess_{secrets.token_urlsafe(24)}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=SESSION_TTL)

    db.execute(
        "INSERT INTO sessions (session_id, agent_id, issued_at, expires_at) VALUES (?, ?, ?, ?)",
        (session_id, req.agent_id, now.isoformat(), expires_at.isoformat()),
    )
    db.commit()

    return AuthResponse(session_token=session_id)
