"""Tests for credential exchange — Step 2."""

import bcrypt
import pytest


class TestAuthExchange:
    def test_valid_exchange_returns_session(self, client, seeded_agent):
        resp = client.post("/v1/auth", json={
            "agent_id": seeded_agent["agent_id"],
            "client_secret": seeded_agent["client_secret"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_token" in data
        assert data["session_token"].startswith("sess_")

    def test_secret_invalidated_after_exchange(self, client, db, seeded_agent):
        # First exchange succeeds
        resp = client.post("/v1/auth", json={
            "agent_id": seeded_agent["agent_id"],
            "client_secret": seeded_agent["client_secret"],
        })
        assert resp.status_code == 200

        # Second exchange with same secret fails
        resp2 = client.post("/v1/auth", json={
            "agent_id": seeded_agent["agent_id"],
            "client_secret": seeded_agent["client_secret"],
        })
        assert resp2.status_code == 401

    def test_wrong_secret_fails(self, client, seeded_agent):
        resp = client.post("/v1/auth", json={
            "agent_id": seeded_agent["agent_id"],
            "client_secret": "wrong_secret",
        })
        assert resp.status_code == 401

    def test_nonexistent_agent_fails(self, client):
        resp = client.post("/v1/auth", json={
            "agent_id": "nonexistent",
            "client_secret": "anything",
        })
        assert resp.status_code == 401

    def test_suspended_agent_cannot_auth(self, client, db, seeded_agent):
        db.execute(
            "UPDATE agents SET status = 'suspended' WHERE agent_id = ?",
            (seeded_agent["agent_id"],),
        )
        db.commit()

        resp = client.post("/v1/auth", json={
            "agent_id": seeded_agent["agent_id"],
            "client_secret": seeded_agent["client_secret"],
        })
        assert resp.status_code == 401

    def test_session_stored_in_db(self, client, db, seeded_agent):
        resp = client.post("/v1/auth", json={
            "agent_id": seeded_agent["agent_id"],
            "client_secret": seeded_agent["client_secret"],
        })
        session_token = resp.json()["session_token"]

        row = db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_token,)
        ).fetchone()
        assert row is not None
        assert row["agent_id"] == seeded_agent["agent_id"]
        assert row["revoked"] == 0
