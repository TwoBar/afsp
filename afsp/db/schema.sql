CREATE TABLE IF NOT EXISTS agents (
  agent_id    TEXT PRIMARY KEY,
  org_id      TEXT NOT NULL,
  name        TEXT NOT NULL,
  role        TEXT,
  status      TEXT NOT NULL DEFAULT 'active',
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS credentials (
  agent_id      TEXT NOT NULL REFERENCES agents(agent_id),
  secret_hash   TEXT NOT NULL,
  issued_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  invalidated   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id    TEXT PRIMARY KEY,
  agent_id      TEXT NOT NULL REFERENCES agents(agent_id),
  issued_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at    DATETIME NOT NULL,
  revoked       INTEGER NOT NULL DEFAULT 0,
  container_id  TEXT
);

CREATE TABLE IF NOT EXISTS views (
  id          TEXT PRIMARY KEY,
  agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
  path        TEXT NOT NULL,
  ops         TEXT NOT NULL,
  flags       TEXT,
  updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS role_templates (
  role    TEXT NOT NULL,
  path    TEXT NOT NULL,
  ops     TEXT NOT NULL,
  flags   TEXT
);

CREATE TABLE IF NOT EXISTS tokens (
  token_id    TEXT PRIMARY KEY,
  grantor     TEXT NOT NULL REFERENCES agents(agent_id),
  grantee     TEXT NOT NULL REFERENCES agents(agent_id),
  path        TEXT NOT NULL,
  ops         TEXT NOT NULL,
  expires_at  DATETIME NOT NULL,
  single_use  INTEGER NOT NULL DEFAULT 0,
  used        INTEGER NOT NULL DEFAULT 0,
  issued_by   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS federated_trust (
  agent_id          TEXT NOT NULL REFERENCES agents(agent_id),
  provider          TEXT NOT NULL,
  provider_subject  TEXT NOT NULL,
  org_id            TEXT NOT NULL,
  created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit (
  audit_id      TEXT PRIMARY KEY,
  agent_id      TEXT NOT NULL REFERENCES agents(agent_id),
  op            TEXT NOT NULL,
  path          TEXT NOT NULL,
  outcome       TEXT NOT NULL,
  session_id    TEXT REFERENCES sessions(session_id),
  token_id      TEXT REFERENCES tokens(token_id),
  timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP,
  container_id  TEXT
);
