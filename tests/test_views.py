"""Tests for agent CRUD and view management — Step 3."""

import json
from datetime import datetime, timedelta, timezone

import pytest


class TestAgentCRUD:
    def test_create_agent(self, client, operator_headers):
        resp = client.post("/v1/agents", json={
            "org_id": "org-1",
            "name": "cfo",
            "role": "finance",
        }, headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "cfo"
        assert data["org_id"] == "org-1"
        assert data["status"] == "active"
        assert data["client_secret"].startswith("sk_afsp_")
        assert data["agent_id"].startswith("cfo-")

    def test_get_agent(self, client, operator_headers):
        create = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "cmo",
        }, headers=operator_headers)
        agent_id = create.json()["agent_id"]

        resp = client.get(f"/v1/agents/{agent_id}", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "cmo"
        # client_secret should not be in GET response
        assert resp.json().get("client_secret") is None

    def test_get_nonexistent_agent(self, client, operator_headers):
        resp = client.get("/v1/agents/nonexistent", headers=operator_headers)
        assert resp.status_code == 404

    def test_delete_agent(self, client, operator_headers):
        create = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "temp",
        }, headers=operator_headers)
        agent_id = create.json()["agent_id"]

        resp = client.delete(f"/v1/agents/{agent_id}", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

        # Verify status changed
        get_resp = client.get(f"/v1/agents/{agent_id}", headers=operator_headers)
        assert get_resp.json()["status"] == "removed"

    def test_suspend_agent(self, client, db, operator_headers):
        create = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "sus",
        }, headers=operator_headers)
        agent_id = create.json()["agent_id"]

        resp = client.patch(f"/v1/agents/{agent_id}/suspend", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

    def test_operator_auth_required(self, client):
        resp = client.post("/v1/agents", json={
            "org_id": "org-1", "name": "noauth",
        })
        assert resp.status_code in (401, 422)


class TestViewManagement:
    def _create_agent(self, client, headers, name="test"):
        resp = client.post("/v1/agents", json={
            "org_id": "org-1", "name": name,
        }, headers=headers)
        return resp.json()["agent_id"]

    def test_declare_view(self, client, operator_headers):
        agent_id = self._create_agent(client, operator_headers)

        resp = client.post(f"/v1/view/{agent_id}", json=[
            {"path": "workspace/finance/**", "ops": ["read", "write"]},
            {"path": "assets/brand/**", "ops": ["read"]},
        ], headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_get_view(self, client, operator_headers):
        agent_id = self._create_agent(client, operator_headers)
        client.post(f"/v1/view/{agent_id}", json=[
            {"path": "workspace/finance/**", "ops": ["read", "write"], "flags": ["write_once"]},
        ], headers=operator_headers)

        resp = client.get(f"/v1/view/{agent_id}", headers=operator_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["path"] == "workspace/finance/**"
        assert data[0]["ops"] == ["read", "write"]
        assert data[0]["flags"] == ["write_once"]
        assert data[0]["source"] == "static"

    def test_replace_view(self, client, operator_headers):
        agent_id = self._create_agent(client, operator_headers)

        # First declaration
        client.post(f"/v1/view/{agent_id}", json=[
            {"path": "old/path/**", "ops": ["read"]},
        ], headers=operator_headers)

        # Replace
        client.post(f"/v1/view/{agent_id}", json=[
            {"path": "new/path/**", "ops": ["write"]},
        ], headers=operator_headers)

        resp = client.get(f"/v1/view/{agent_id}", headers=operator_headers)
        data = resp.json()
        assert len(data) == 1
        assert data[0]["path"] == "new/path/**"

    def test_add_to_view(self, client, operator_headers):
        agent_id = self._create_agent(client, operator_headers)
        client.post(f"/v1/view/{agent_id}", json=[
            {"path": "workspace/finance/**", "ops": ["read"]},
        ], headers=operator_headers)

        client.patch(f"/v1/view/{agent_id}", json={
            "path": "workspace/extra/**", "ops": ["read", "write"],
        }, headers=operator_headers)

        resp = client.get(f"/v1/view/{agent_id}", headers=operator_headers)
        assert len(resp.json()) == 2

    def test_remove_from_view(self, client, operator_headers):
        agent_id = self._create_agent(client, operator_headers)
        client.post(f"/v1/view/{agent_id}", json=[
            {"path": "workspace/a/**", "ops": ["read"]},
            {"path": "workspace/b/**", "ops": ["read"]},
        ], headers=operator_headers)

        view = client.get(f"/v1/view/{agent_id}", headers=operator_headers).json()
        path_id = view[0]["id"]

        resp = client.delete(f"/v1/view/{agent_id}/{path_id}", headers=operator_headers)
        assert resp.status_code == 200

        updated = client.get(f"/v1/view/{agent_id}", headers=operator_headers).json()
        assert len(updated) == 1

    def test_view_includes_active_sgts(self, client, db, operator_headers):
        agent_a = self._create_agent(client, operator_headers, "agentA")
        agent_b = self._create_agent(client, operator_headers, "agentB")

        # Static view for B
        client.post(f"/v1/view/{agent_b}", json=[
            {"path": "workspace/b/**", "ops": ["read"]},
        ], headers=operator_headers)

        # Issue SGT from A to B
        client.post("/v1/tokens", json={
            "grantor": agent_a,
            "grantee": agent_b,
            "path": "workspace/handoffs/file.txt",
            "ops": ["read"],
            "ttl": 3600,
        }, headers=operator_headers)

        view = client.get(f"/v1/view/{agent_b}", headers=operator_headers).json()
        assert len(view) == 2
        sources = {v["source"] for v in view}
        assert sources == {"static", "sgt"}

    def test_expired_sgts_excluded(self, client, db, operator_headers):
        agent_a = self._create_agent(client, operator_headers, "agentA")
        agent_b = self._create_agent(client, operator_headers, "agentB")

        # Static view for B
        client.post(f"/v1/view/{agent_b}", json=[
            {"path": "workspace/b/**", "ops": ["read"]},
        ], headers=operator_headers)

        # Issue SGT with 0 TTL (already expired)
        client.post("/v1/tokens", json={
            "grantor": agent_a,
            "grantee": agent_b,
            "path": "workspace/handoffs/file.txt",
            "ops": ["read"],
            "ttl": 0,
        }, headers=operator_headers)

        view = client.get(f"/v1/view/{agent_b}", headers=operator_headers).json()
        # Only static view, expired SGT excluded
        assert len(view) == 1
        assert view[0]["source"] == "static"
