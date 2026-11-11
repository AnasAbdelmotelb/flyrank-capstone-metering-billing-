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
