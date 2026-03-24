# AFSP — Agent File Scope Protocol

> v0.1 MVP — standalone — Python 3.11+

AFSP is a filesystem perception layer for agents. It constructs a declared filesystem view for each agent before it starts, enforcing boundaries at the OS level. Agents perceive a unified filesystem regardless of where files physically live. AFSP is invisible to the agents it governs.

> The agent wakes up inside a complete filesystem the operator designed. Other paths do not exist — not denied, not unreachable. Absent.

---

## What this is

Every agent that runs on a host has implicit access to whatever the filesystem exposes. In multi-agent systems, agents can read each other's working files, overwrite artifacts, and operate without any declared boundary between them.

AFSP solves this with a single primitive: before an agent starts, its filesystem is constructed. Not filtered. Constructed. The agent cannot reason about what it cannot see because from its perspective there is nothing to see.

This project is a standalone implementation of the AFSP protocol. It is built as infrastructure first — separate from any agent platform — so the design stays clean and the interface stays portable.

---

## Core concepts

### View declaration

The operator declares what filesystem reality looks like for each agent in an `afsp.yml` file. This is registered into the control plane database. The file is a deployment descriptor — after registration the database is authoritative.
```yaml
name: cfo
role: finance
runtime: python
entrypoint: main.py
view:
  - path: workspace/finance/**
    ops: [read, write]
  - path: workspace/handoffs/inbound/**
    ops: [read]
  - path: workspace/handoffs/outbound/**
    ops: [write]
    flags: [write_once]
  - path: assets/brand/**
    ops: [read]
```

### Unified landscape

An agent's experience of files accessed via AFSP is functionally equivalent to working with local files. The agent can read, write, execute, import, and reference files using standard shell operations regardless of whether files live on local disk, S3, or NFS. AFSP materialises remote paths locally before the agent starts. The only observable difference is first-access latency on remote-backed paths.

### Scope Grant Tokens (SGTs)

When one agent produces an artifact another agent needs, the job engine issues an SGT. The file appears in the receiving agent's view. When the token expires or is consumed, the file disappears. The agent experiences this as a file that exists, then ceases to exist. It never experiences a permission boundary.

### ENOENT not EACCES

Out-of-view paths return `ENOENT` — no such file or directory. Not `EACCES` — permission denied. The agent cannot distinguish a forbidden path from a nonexistent one.

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
│   ├── runtime/      watcher, projection, enforcement, materialise
│   ├── store/        local disk adapter, S3 stub
│   └── cli/          Click CLI
├── tests/
├── var/afsp/
│   ├── agents/       drop afsp.yml files here
│   ├── db/           afsp.db
│   ├── volumes/      managed workspace storage
│   └── logs/         audit log
├── BUILD_GUIDE.md
└── README.md
```

---

## Workspace layout
```
/var/afsp/volumes/
├── handoffs/
│   ├── inbound/       shared — read for receivers via SGT
│   └── outbound/      shared — write-once for producers
├── shared/
│   └── brand-assets/  shared — read-only for all agents
└── agents/
    ├── cmo/           private — visible only to cmo-agent
    ├── cfo/           private — visible only to cfo-agent
    └── analytics/     private — visible only to analytics-agent
```

---

## Control plane API

| Method | Path | Purpose |
|---|---|---|
| POST | /v1/auth | exchange credentials for session token |
| POST | /v1/agents | create agent identity |
| GET | /v1/agents/{id} | inspect agent |
| PATCH | /v1/agents/{id}/suspend | suspend — all sessions revoked immediately |
| POST | /v1/view/{agent_id} | declare or replace view |
| GET | /v1/view/{agent_id} | get current view |
| POST | /v1/tokens | issue SGT |
| DELETE | /v1/tokens/{id} | revoke token early |
| GET | /v1/audit | query audit log |

---

## CLI
```bash
afsp push {name}           deploy agent from afsp.yml
afsp start {name}          start agent container
afsp stop {name}           stop agent container
afsp suspend {name}        revoke all sessions, stop container
afsp inspect {name}        show agent identity and status
afsp view {name}           show exactly what the agent perceives
afsp logs {name}           stream agent logs
afsp token issue           issue SGT manually
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

## Out of scope for v1

- S3 backing store (stub only)
- NFS backing store
- OIDC federated authentication
- Kubernetes CRD
- Multi-host workspace federation
- Execution routing or runtime management
- Tool access control
- Network traffic scoping
- Content-aware access control
- WebUI

---

## Design principles

- View construction not permission checking — the filesystem is built, not filtered
- Invisibility over denial — out-of-view paths return ENOENT, never EACCES
- Identity-bound views — the view belongs to the agent identity, not the container
- Least view by default — new agents see nothing, access is explicitly declared
- Unified landscape — remote and local paths are indistinguishable to the agent
- Deployment is an operator concern — agents never know about AFSP
- Control plane ownership — the database is authoritative, not the afsp.yml file

---

## Prior art and positioning

AFSP sits in a gap between existing tools. SPIFFE/SPIRE handles workload identity but has no opinion on filesystem scope. Linux Landlock enforces path-level restrictions but has no identity awareness. OPA makes policy decisions but has no enforcement mechanism. AgentFS (Turso) provides copy-on-write overlays but no access control model. NVIDIA OpenShell provides declarative sandbox policies but no cross-runtime portability or identity federation.

No existing tool binds agent identity to declarative filesystem permissions with kernel-level enforcement across a portable protocol. That is the gap AFSP fills.

---

## Stack

Python 3.11+ · FastAPI · SQLite · Click · bcrypt · PyJWT · watchdog · PyYAML · pytest · uvicorn

---

*Authors: Barnaba Barcellona + Claude — March 2026*
