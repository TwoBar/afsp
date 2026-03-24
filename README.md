# AFSP — Agent File Scope Protocol

[![CI](https://github.com/TwoBar/afsp/actions/workflows/ci.yml/badge.svg)](https://github.com/TwoBar/afsp/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

> v1.0 — standalone reference implementation — Python 3.11+

AFSP is a filesystem perception layer for agents. It constructs a declared filesystem view for each agent before it starts, enforcing boundaries at the OS level. Agents perceive a unified filesystem regardless of where files physically live. AFSP is invisible to the agents it governs.

> The agent wakes up inside a complete filesystem the operator designed. Other paths do not exist — not denied, not unreachable. Absent.

---

## Quick start

```bash
# Clone and install
git clone https://github.com/TwoBar/afsp.git && cd afsp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — set a strong AFSP_OPERATOR_TOKEN

# Run the control plane
export $(cat .env | xargs)
uvicorn afsp.api.main:app --reload

# Run tests
pytest
```

---

## What this is

Every agent that runs on a host has implicit access to whatever the filesystem exposes. In multi-agent systems, agents can read each other's working files, overwrite artifacts, and operate without any declared boundary between them.

AFSP solves this with a single primitive: before an agent starts, its filesystem is constructed. Not filtered. Constructed. The agent cannot reason about what it cannot see because from its perspective there is nothing to see.

This project is a reference implementation. The control plane API and database are one way to do it — the underlying model (declarative view construction with ENOENT semantics) can be implemented against any filesystem layer that supports mount namespaces. This repo is built as infrastructure first, separate from any agent platform, so the design stays clean and the interface stays portable.

---

## Core concepts

### View declaration

The operator declares what filesystem reality looks like for each agent in an `afsp.yml` file. This is registered into the control plane database. The file is a deployment descriptor — after registration the database is authoritative.

All paths are relative to the volumes root (`AFSP_VOLUMES_PATH`, defaults to `/var/afsp/volumes/`). The operator organises this root however they like — AFSP imposes no directory structure within it.
```yaml
name: cfo
role: finance
view:
  - path: agents/cfo/**
    ops: [read, write]
  - path: shared/datasets/**
    ops: [read]
  - path: shared/reports/**
    ops: [read, write]
```

Inside the container, the agent sees these as `/workspace/agents/cfo/`, `/workspace/shared/datasets/`, etc. Paths outside its view do not exist.

### Scope Grant Tokens (SGTs)

When one agent needs to share a file with another, the operator (or an orchestrator) issues an SGT — a time-bounded, optionally single-use token that temporarily expands the receiving agent's view. The file appears. When the token expires or is consumed, the file disappears. The agent never experiences a permission boundary.

SGTs work with any path. There is no required directory layout — shared spaces, private workspaces, group-scoped clusters, or flat structures all work. AFSP is a scoping primitive, not a workspace manager.

### ENOENT not EACCES

Out-of-view paths return `ENOENT` — no such file or directory. Not `EACCES` — permission denied. The agent cannot distinguish a forbidden path from a nonexistent one.

### Known limitation: parent directory leakage

When a view declares a deep path like `deep/nested/child/**`, the parent directories (`deep/`, `deep/nested/`) must exist for the mount to work. In v1, these parents are plain directories — an agent listing `deep/` could see sibling names even if it has no access to them. This leaks structure information.

v2 will address this with **synthetic parents** — empty, read-only intermediate directories that contain only the declared children. Until then, operators who need strict isolation should keep view paths shallow or colocate related views under a common prefix.

---

## Architecture
```
agent process
     │  standard shell — ls, cat, cp, python, bash
     ↓
mount namespace (kernel-enforced)
     │  only declared paths exist
     ↓
AFSP enforcement layer
     │  validates ops, writes audit log
     ↓
materialisation cache
     │  remote paths fetched to local temp
     ↓
backing store
     local disk / S3 / NFS
```

## Session and identity chain
```
AFSP_AGENT_ID + AFSP_CLIENT_SECRET   (injected at container boot)
        ↓
POST /v1/auth  →  session_token       (secret invalidated immediately)
        ↓
session_token → agent_id              (sessions table lookup)
        ↓
agent_id → views + active SGTs        (full view union)
        ↓
projection layer assembles bind mounts
        ↓
agent starts inside its declared view
```

---

## Repository layout
```
afsp/
├── afsp/
│   ├── api/          control plane — FastAPI
│   ├── db/           schema, migrations
│   ├── runtime/      watcher, projection, enforcement, materialise, pathutil
│   ├── store/        local disk adapter, S3 stub
│   └── cli/          Click CLI
├── tests/
├── examples/         sample afsp.yml files
├── var/afsp/
│   ├── agents/       drop afsp.yml files here
│   ├── db/           afsp.db
│   ├── volumes/      managed workspace storage
│   └── logs/         audit log
├── .env.example
├── .github/workflows/ CI pipeline
├── CONTRIBUTING.md
├── LICENSE
├── pyproject.toml
└── README.md
```

---

## Example workspace layouts

AFSP doesn't prescribe a directory structure. Views can point to any path. Here are common patterns:

**Private workspaces + shared space**
```
/data/
├── shared/              read-only for all agents
├── team-finance/        read/write for finance group
├── team-engineering/    read/write for engineering group
├── agent-cfo/           private to cfo agent
└── agent-analyst/       private to analyst agent
```

**Flat project structure**
```
/projects/
├── frontend/            agent-frontend: read/write
├── backend/             agent-backend: read/write
├── shared-types/        both agents: read
└── deploy/              agent-deployer: read/write, others: read via SGT
```

**Single workspace, scoped access**
```
/workspace/
├── src/                 coding-agent: read/write
├── tests/               test-agent: read/write, coding-agent: read
├── docs/                docs-agent: read/write
└── .env                 no agent sees this
```

---

## Control plane API

| Method | Path | Purpose |
|---|---|---|
| POST | /v1/auth | exchange credentials for session token |
| POST | /v1/agents | create agent identity |
| GET | /v1/agents | list all agents (filterable by status) |
| GET | /v1/agents/{id} | inspect agent |
| DELETE | /v1/agents/{id} | remove agent |
| PATCH | /v1/agents/{id}/suspend | suspend — all sessions revoked immediately |
| POST | /v1/view/{agent_id} | declare or replace view |
| GET | /v1/view/{agent_id} | get current view |
| PATCH | /v1/view/{agent_id} | add entry to view |
| DELETE | /v1/view/{agent_id}/{path_id} | remove entry from view |
| POST | /v1/tokens | issue SGT |
| GET | /v1/tokens/{id} | inspect token |
| DELETE | /v1/tokens/{id} | revoke token early |
| GET | /v1/audit | query audit log |

---

## CLI
```bash
afsp push {name}           deploy agent from afsp.yml
afsp start {name}          start agent container (v2)
afsp stop {name}           stop agent container (v2)
afsp suspend {name}        revoke all sessions, stop container
afsp inspect {name}        show agent identity and status
afsp view {name}           show exactly what the agent perceives
afsp logs {name}           stream agent logs (v2)
afsp token-issue           issue SGT manually
afsp audit --agent {name}  query audit log for agent
```

`afsp view {name}` is the primary diagnostic tool. It prints the filesystem tree exactly as the agent perceives it at this moment — static view plus any active SGTs with expiry times.

---

## Compliance tiers

| Tier | Agent type | Auth | Container |
|---|---|---|---|
| 0 | Stateless external | mTLS or OIDC | Ephemeral per invocation |
| 1 | Containerised, unaware | env vars | Persistent |
| 2 | Containerised, SDK-aware | env vars + SDK | Persistent |

All tiers receive the same filesystem view. Tier affects authentication and container lifecycle, not perceived environment.

---

## v2 Roadmap

- Synthetic parent directories — empty, read-only intermediates that reveal only declared children
- Arbitrary host path mounts — views spanning multiple unrelated host directories
- S3 backing store
- NFS backing store
- Unified landscape — remote paths appear as local files transparently
- OIDC federated authentication
- Kubernetes CRD
- Multi-host workspace federation
- Container lifecycle management (start/stop/logs)
- Rate limiting on API endpoints
- Session management endpoints (validate, list, revoke individual)
- WebUI

## Out of scope

- Execution routing or runtime management
- Tool access control
- Network traffic scoping
- Content-aware access control

---

## Design principles

- View construction not permission checking — the filesystem is built, not filtered
- Invisibility over denial — out-of-view paths return ENOENT, never EACCES
- Identity-bound views — the view belongs to the agent identity, not the container
- Least view by default — new agents see nothing, access is explicitly declared
- Layout-agnostic — AFSP is a scoping primitive, not a workspace manager. Any directory structure works
- Deployment is an operator concern — agents never know about AFSP
- Control plane ownership — the database is authoritative, not the afsp.yml file

---

## Prior art and positioning

AFSP sits in a gap between existing tools. SPIFFE/SPIRE handles workload identity but has no opinion on filesystem scope. Linux Landlock enforces path-level restrictions but has no identity awareness. OPA makes policy decisions but has no enforcement mechanism. AgentFS (Turso) provides copy-on-write overlays but no access control model. NVIDIA OpenShell provides declarative sandbox policies but no cross-runtime portability or identity federation.

No existing tool binds agent identity to declarative filesystem permissions with kernel-level enforcement across a portable protocol. That is the gap AFSP fills.

---

## Stack

Python 3.11+ · FastAPI · SQLite · Click · bcrypt · watchdog · PyYAML · pytest · uvicorn

---

*Authors: Barnaba Barcellona + Claude — March 2026*
