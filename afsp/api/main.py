"""FastAPI application for AFSP control plane."""

import os

from fastapi import Depends, FastAPI, Header, HTTPException

from afsp.db.db import get_connection, init_db

app = FastAPI(title="AFSP Control Plane", version="1.0.0")

_db_conn = None


def get_db():
    global _db_conn
    if _db_conn is None:
        _db_conn = init_db()
    return _db_conn


def reset_db(conn):
    """Replace the database connection (used in tests)."""
    global _db_conn
    _db_conn = conn


OPERATOR_TOKEN = os.environ.get("AFSP_OPERATOR_TOKEN", "")


def require_operator(authorization: str = Header(None)):
    if not OPERATOR_TOKEN:
        raise HTTPException(status_code=500, detail="AFSP_OPERATOR_TOKEN not configured")
    if authorization != f"Bearer {OPERATOR_TOKEN}":
        raise HTTPException(status_code=401, detail="Invalid operator token")


from afsp.api.auth import router as auth_router
from afsp.api.agents import router as agents_router
from afsp.api.views import router as views_router
from afsp.api.tokens import router as tokens_router

app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(views_router)
app.include_router(tokens_router)
