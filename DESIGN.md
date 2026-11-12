# Usage Metering & Billing Service

## Problem and scope
Measure monthly tenant usage, reject actions exceeding plan limits, and calculate
reproducible costs. Two plans, two usage dimensions, one simulated generation
endpoint. Non-goal: real AI requests, real payments, invoicing, or proration.

## Data and layers
FastAPI HTTP boundary -> MeterService -> SQLite transactions and migrations.
Tenants hold hashed API keys; subscriptions reference a tenant and a plan.
Plans hold monthly API-call and token quotas. Usage events hold both dimensions,
UTC month, request fingerprint, pricing version, cost in USD micro-units, and the
original response. Index monthly tenant usage; uniquely constrain tenant + key.

## API contract
`POST /generate`: Bearer tenant API key, Idempotency-Key, JSON token counts.
`GET /usage`: authenticated current UTC calendar month totals and plan limits.
`GET /health`: readiness. Interactive API documentation: `/docs`.
Token counts are integers; cached_input_tokens is a subset of input_tokens;
reasoning_tokens is a subset of output_tokens. Both subsets must be <= totals.
The quota counts input + output, including each subset exactly once.

## Correctness rules
Acquire a SQLite BEGIN IMMEDIATE write transaction before checking the existing
idempotency key, subscription, or quotas. Accept requests whose projected usage
equals the limit; reject greater usage with 429 and Retry-After until next UTC
month. Inactive subscriptions return 402. Rejected actions write no usage.
A retry returns the persisted original response even after a month or plan change.
Reusing a key with a changed body returns 409. The dummy action and event commit
together; external actions would require a separate durable execution design.

## Pinned pricing v1 (illustrative, not provider rates)
1 API call = 1,000 USD micro-units; fresh input token = 2; cached input = 1;
output token = 8. Reasoning is already included in output. No float arithmetic.
Free: 1,000 calls / 100,000 tokens. Pro: 10,000 calls / 1,000,000 tokens.

## Delivery gates
1. Design and local runnable scaffold.
2. Atomic metering, quotas, pricing, and concurrency evidence.
3. Stripe test Checkout and verified, deduplicated subscription webhooks.
4. Background monthly rollup job with durable retries and failure alerts;
   full evidence and public repository submission.

Stripe test integration and the leased background rollup worker are implemented.
Verified webhook events retrieve current subscription state under the write lock;
event deduplication and the mirror update commit together. A separate worker
produces closed-month rollups, retries failures, recovers expired leases, and
persists failure alerts exposed through authenticated HTTP reads. Public GitHub
history is configured. Genuine Stripe Checkout, signed CLI delivery, duplicate
replay, signature rejection and cancellation were verified on 2026-11-13.
