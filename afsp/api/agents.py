"""Agent CRUD endpoints."""

import json
import uuid
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from afsp.api.main import get_db, require_operator

router = APIRouter()


class CreateAgentRequest(BaseModel):
    org_id: str
    name: str
    role: Optional[str] = None


class AgentResponse(BaseModel):
    agent_id: str
    org_id: str
    name: str
    role: Optional[str]
    status: str
    client_secret: Optional[str] = None


@router.post("/v1/agents", response_model=AgentResponse, dependencies=[Depends(require_operator)])
def create_agent(req: CreateAgentRequest):
    db = get_db()
    agent_id = f"{req.name}-{uuid.uuid4().hex[:4]}"
    client_secret = f"sk_afsp_{uuid.uuid4().hex}"

    secret_hash = bcrypt.hashpw(client_secret.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    db.execute(
        "INSERT INTO agents (agent_id, org_id, name, role) VALUES (?, ?, ?, ?)",
        (agent_id, req.org_id, req.name, req.role),
    )
    db.execute(
        "INSERT INTO credentials (agent_id, secret_hash) VALUES (?, ?)",
        (agent_id, secret_hash),
    )
    db.commit()

    return AgentResponse(
        agent_id=agent_id,
        org_id=req.org_id,
        name=req.name,
        role=req.role,
        status="active",
        client_secret=client_secret,
    )


@router.get("/v1/agents/{agent_id}", response_model=AgentResponse, dependencies=[Depends(require_operator)])
def get_agent(agent_id: str):
    db = get_db()
    row = db.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse(
        agent_id=row["agent_id"],
        org_id=row["org_id"],
        name=row["name"],
        role=row["role"],
        status=row["status"],
    )


@router.delete("/v1/agents/{agent_id}", dependencies=[Depends(require_operator)])
def delete_agent(agent_id: str):
    db = get_db()
    row = db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.execute("UPDATE agents SET status = 'removed' WHERE agent_id = ?", (agent_id,))
    db.execute("UPDATE sessions SET revoked = 1 WHERE agent_id = ?", (agent_id,))
    db.commit()
    return {"status": "removed", "agent_id": agent_id}


@router.patch("/v1/agents/{agent_id}/suspend", dependencies=[Depends(require_operator)])
def suspend_agent(agent_id: str):
    db = get_db()
    row = db.execute("SELECT agent_id FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    db.execute("UPDATE sessions SET revoked = 1 WHERE agent_id = ?", (agent_id,))
    db.execute("UPDATE agents SET status = 'suspended' WHERE agent_id = ?", (agent_id,))
    db.commit()
    return {"status": "suspended", "agent_id": agent_id}
