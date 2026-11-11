# LLM Usage Metering & Billing Service

FastAPI + SQLite backend for tenant-scoped monthly usage, quotas, and costs.
Stripe test Checkout, signed subscription webhooks, and a durable monthly rollup
worker are implemented. Local automated checks pass. A genuine Stripe test
Checkout and replay still need account-specific verification before submission.

## Architecture

```text
Bearer API key -> FastAPI validation -> MeterService -> SQLite
                                          |
                              single write transaction
                              deduplicate -> quota -> event
GET /usage -> tenant/month rollup -> used, limit, cost
Stripe test Checkout -> signed webhook -> current subscription -> tenant plan
Separate worker -> persistent jobs -> monthly_rollups / failure alerts
```

See [DESIGN.md](DESIGN.md) for contracts, decisions, and the phase checklist.

## Run locally

Requires Python 3.11+. No paid services, Docker, or AI key needed.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.seed
.venv/bin/python -m app.run
```

The seed command creates Free and Pro demo tenants and prints their randomly
generated API keys once. Save them locally. Re-running seed preserves existing
data and credentials. API keys are stored as SHA-256 hashes; these keys are
random 256-bit credentials, not human passwords.
If you lose a demo key, run `.venv/bin/python -m app.seed --rotate-keys` to replace
both demo keys while preserving usage.

Open http://127.0.0.1:8000/docs for the interactive API. Use Authorize to enter a
seeded API key. `/health` needs no authentication. The server binds to localhost.

Optional configuration: export `DATABASE_PATH=/path/to/billing.db` before both
seed and run commands. Default: `billing.db` in the working directory.
`.env.example` documents settings; a project-root `.env` is loaded automatically.
Explicit environment variables take precedence. Copy `.env.example` to `.env`
and replace Stripe placeholders locally when ready for payment testing.

```bash
export API_KEY='paste-your-seeded-key-here'
curl -sS http://127.0.0.1:8000/generate \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Idempotency-Key: example-001' \
  -H 'Content-Type: application/json' \
  -d '{"input_tokens":1000,"cached_input_tokens":400,"output_tokens":500,"reasoning_tokens":200}'
curl -sS http://127.0.0.1:8000/usage -H "Authorization: Bearer $API_KEY"
```

Repeating the POST returns the same event and response without consuming quota.
Changing its body while keeping the key returns 409. Use a new key per new action.

## Quotas and pricing

| Plan | API calls/month | AI tokens/month |
| --- | ---: | ---: |
| Free | 1,000 | 100,000 |
| Pro | 10,000 | 1,000,000 |

Months use UTC calendar boundaries. Exactly reaching a limit succeeds; exceeding
either limit returns 429 with Retry-After until reset. Inactive subscriptions
return 402. Rejections consume no usage. Every successful generation counts one
API call, including a generation with zero tokens.

`input_tokens` includes `cached_input_tokens`; `output_tokens` includes
`reasoning_tokens`. Quota counts input + output once. Cost v1 in
[app/pricing.py](app/pricing.py) uses integer USD micro-units (1 USD = 1,000,000):

```text
1000 per call + 2 * (input - cached) + 1 * cached + 8 * output
Example above: 1000 + 1200 + 400 + 4000 = 6600 micro-USD ($0.0066)
```

These are illustrative pinned rates, not current provider prices. `/usage` sums
persisted event costs rather than repricing history.

## Verify

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.check_secrets
```

Tests cover concurrent retries, concurrent quota races, boundaries, exact prices,
isolation, validation, persistence, and month rollover. Evidence: [EVIDENCE.md](EVIDENCE.md).

## Stripe test setup

Follow [STRIPE_SETUP.md](STRIPE_SETUP.md) for the exact account, CLI, Checkout,
webhook, and evidence steps. The recurring subscription price is independent of
the illustrative usage-cost calculator; this project does not invoice usage.

`POST /billing/checkout` requires a tenant Bearer key. It returns a hosted URL,
reuses an unexpired session, and rejects a second active Stripe subscription.
Return redirects do not grant access. Only verified events synchronize plans.
The webhook handles Checkout completion and subscription create/update/delete.
Each event ID and its state change commit together. The handler retrieves current
Stripe state under the write lock to protect against out-of-order snapshots.
Unknown tenants and unrelated event types are ignored. Unknown prices are rejected.
Only the configured Pro price, quantity one, and test objects are accepted.

Active/trialing subscriptions receive Pro; other ongoing statuses block billable
requests with 402. Canceled/expired subscriptions return to active Free, retaining
the month's usage. Upgrades and downgrades do not reset usage or change historical
costs. Multiple simultaneous subscriptions require operator reconciliation.

## Background processing

The documented run command starts both Uvicorn and a separate worker process.
For independent operation use `.venv/bin/python -m app.worker` and
`.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000` in separate terminals.
`.venv/bin/python -m app.worker --once` schedules and drains currently ready work.

The worker schedules a unique tenant/month job for last month and historical
closed months with usage. It checks every two seconds. Jobs have a 60-second
lease, three attempts, and exponential backoff (2 then 4 seconds). Committed
rollup and completion are atomic; interrupted jobs recover after lease expiry.
Final failures create a durable `job_alerts` row and emit an error on stderr.
Authenticated `GET /jobs/alerts` shows only the tenant's alerts;
`GET /usage/history` shows up to 24 closed-month summaries. No external email or
Slack notifications are sent. Current-month `/usage` always reads source events.

## Remaining work and limitations

- Complete real Stripe test Checkout and CLI replay evidence (see setup guide).
- Repeat account-dependent setup on a fresh clone before portal submission.
- SQLite serializes writes; this local demo is intended for modest workloads.
  Stripe network calls have an 8-second timeout and hold the write lock, trading
  throughput for simple ordering. Failed calls leave events retryable.
- Idempotency records are retained indefinitely. No live AI calls or external
  side effects are executed; exactly-once behavior applies to local metering.
- No self-service tenant creation or key rotation HTTP endpoint yet.

Implementation references: [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
and [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/),
[Stripe webhooks](https://docs.stripe.com/webhooks), and
[Stripe Checkout](https://docs.stripe.com/api/checkout/sessions/create).
