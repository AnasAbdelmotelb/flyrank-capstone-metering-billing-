# LLM Usage Metering & Billing Service

FastAPI + SQLite backend for tenant-scoped monthly usage, quotas, and costs.
**Current milestone:** design and core billing. Stripe and background jobs are
pending; this is not yet a complete capstone submission.

## Architecture

```text
Bearer API key -> FastAPI validation -> MeterService -> SQLite
                                          |
                              single write transaction
                              deduplicate -> quota -> event
GET /usage -> tenant/month rollup -> used, limit, cost
```

See [DESIGN.md](DESIGN.md) for contracts, decisions, and the phase checklist.

## Run locally

Requires Python 3.11+. No paid services, Docker, or AI key needed.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
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
`.env.example` documents it; `.env` is not automatically loaded.

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
```

Tests cover concurrent retries, concurrent quota races, boundaries, exact prices,
isolation, validation, persistence, and month rollover. Evidence: [EVIDENCE.md](EVIDENCE.md).

## Remaining work and limitations

- Stripe test Checkout, signature verification, webhook deduplication and plan sync.
- Durable background rollup job, retries, and failure alerts.
- Create a dedicated public GitHub repository and complete submission evidence.
- SQLite serializes writes; this local demo is intended for modest workloads.
- Idempotency records are retained indefinitely. No live AI calls or external
  side effects are executed; exactly-once behavior applies to local metering.
- No self-service tenant creation or key rotation HTTP endpoint yet.

Implementation references: [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
and [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/).
