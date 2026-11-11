CREATE TABLE checkout_sessions (
    tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
    session_id TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE stripe_links (
    subscription_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    customer_id TEXT NOT NULL,
    stripe_status TEXT NOT NULL
);
CREATE INDEX stripe_links_tenant ON stripe_links(tenant_id);
CREATE TABLE stripe_events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    month TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','done','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_until INTEGER,
    UNIQUE(tenant_id, month)
);
CREATE INDEX jobs_ready ON jobs(status, available_at);
CREATE TABLE monthly_rollups (
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    month TEXT NOT NULL,
    api_calls INTEGER NOT NULL,
    ai_tokens INTEGER NOT NULL,
    cost_microusd INTEGER NOT NULL,
    PRIMARY KEY(tenant_id, month)
);
CREATE TABLE job_alerts (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
