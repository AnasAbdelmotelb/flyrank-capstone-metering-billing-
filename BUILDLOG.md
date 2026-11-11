# Build log

## 2026-11-11 - Design and core billing

Codex read the capstone brief and proposed FastAPI + SQLite for a local first
milestone. AI authored the design, migrations, HTTP/data/service layers, seed,
pricing calculator, tests, and documentation. The user has not yet reviewed or
explained this code; do not claim independent authorship or understanding.

Important decisions: serialize quota checks with writes; scope idempotency keys
to tenants; persist original responses; model cached/reasoning counts as subsets;
pin illustrative integer pricing; derive tenant identity from hashed random API
keys rather than accepting an arbitrary tenant ID in the request.

Correction during implementation: the initial event INSERT had twelve SQL
placeholders for eleven columns; Codex corrected it before running tests.

Verification: 15 tests passed. The installed Starlette version emits a TestClient
deprecation warning recommending httpx2; current httpx-based tests still pass.
No real Stripe flow has been tested or claimed. Background processing and public
repository creation remain pending. See EVIDENCE.md for actual recorded output.

Live HTTP smoke also passed against Uvicorn. The initial sandbox blocked port
binding and localhost requests; approved executions verified the service.
Added an explicit demo-key rotation CLI because seeded credentials are shown only
once. Local Git history preserves the design and core milestones separately.

## 2026-11-11 - Stripe, background processing, and repository

The user authorized pushing and supplied the public GitHub destination. Codex
pushed the existing two local commits, expanded ignore rules for env variants,
SQLite files and local tools, and implemented official Stripe SDK test Checkout,
raw-body signature verification, atomic event deduplication, and current-state
subscription synchronization. Canceling returns a tenant to Free without erasing
usage. SDK/network errors are sanitized and leave event processing retryable.

AI also authored durable rollup jobs with leases, three attempts, backoff, crash
recovery, atomic rollup completion, tenant-scoped persisted alerts, and stderr
failure messages. The run command launches API and worker processes together.

Tests initially exposed a Stripe SDK v16 API change: API resources no longer
support dict.get. Codex corrected the gateway to convert resources via to_dict
before using application logic. Migration locking was tightened after reviewing
concurrent API/worker startup. All 27 tests then passed, with one pre-existing
Starlette deprecation warning.

Homebrew CLI installation failed because Apple Command Line Tools are outdated;
the local official prebuilt binary path avoids changing system development tools.
No Stripe account was created by the agent, no secret values were printed, and
no real-account Checkout verification is claimed. The user must configure their
test account locally and complete browser authentication/payment steps.
