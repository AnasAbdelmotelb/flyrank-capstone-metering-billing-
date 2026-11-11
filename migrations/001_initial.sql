CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY,
    api_limit INTEGER NOT NULL CHECK(api_limit >= 0),
    token_limit INTEGER NOT NULL CHECK(token_limit >= 0)
);
INSERT OR IGNORE INTO plans VALUES ('free', 1000, 100000), ('pro', 10000, 1000000);
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    api_key_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS subscriptions (
    tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
    plan_id TEXT NOT NULL REFERENCES plans(id),
    status TEXT NOT NULL CHECK(status IN ('active', 'unpaid', 'canceled'))
);
CREATE TABLE IF NOT EXISTS usage_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    month TEXT NOT NULL,
    created_at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    api_calls INTEGER NOT NULL CHECK(api_calls = 1),
    tokens INTEGER NOT NULL CHECK(tokens >= 0),
    cost_microusd INTEGER NOT NULL CHECK(cost_microusd >= 0),
    pricing_version TEXT NOT NULL,
    response TEXT NOT NULL,
    UNIQUE(tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS usage_tenant_month ON usage_events(tenant_id, month);
