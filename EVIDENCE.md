# Evidence

Executed locally on 2026-11-11 using `.venv/bin/python -m pytest -q`:

```text
...............                                                          [100%]
15 passed, 1 warning in 0.88s
```

Warning: installed Starlette TestClient deprecates httpx in favor of httpx2.

Live server verification, `.venv/bin/python -m scripts.smoke`:

```text
Live HTTP smoke passed: identical retry, one call, 1500 tokens, 6600 micro-USD
```

The smoke script creates an isolated tenant and removes its own test data after
the probe. Start the API before running it.

| Requirement | Reproducible proof |
| --- | --- |
| One event under retry, same original response | `test_retry_and_conflict`; `test_concurrent_retries` submits 20 requests on 8 threads, asserts one event ID and one call |
| Conflicting key payload rejected | `test_retry_and_conflict` asserts 409 |
| Quota boundaries and 429 | `test_token_limit_and_retry_after` accepts exactly 100000 tokens and rejects next token; `test_concurrent_quota_boundary` permits one of 12 concurrent requests with one call remaining |
| Inactive subscription returns 402 | `test_auth_isolation_and_inactive_subscription` |
| Monthly usage and cost | `test_pricing_and_rollup` asserts 1500 tokens, 1 call, and 6600 micro-USD |
| Cached and reasoning token rules | `test_pricing_and_rollup`: 1000 input including 400 cached; 500 output including 200 reasoning; total 6600 |
| Tenant isolation and key scope | `test_auth_isolation_and_inactive_subscription` uses the same idempotency key for two tenants and checks separate usage |
| Persistence and migrations | `test_persistence` reopens connections and reruns migrations without losing usage |
| Validation and no rejected usage | Seven `test_bad_input` cases assert 422 and zero events |
| Month rollover and historical retries | `test_utc_month_reset_and_old_retry` crosses December/January |

## Stripe and background processing - 2026-11-11

Executed `.venv/bin/python -m pytest -q` after implementation:

```text
...........................                                              [100%]
27 passed, 1 warning in 0.66s
```

| Requirement | Actual passing automated proof |
| --- | --- |
| Authenticated Checkout, repeated session reuse, Free -> Pro limits | `test_checkout_auth_and_reuse` (Stripe network calls replaced by fixtures; real SDK signature verification) |
| Forged, expired, and live-mode events rejected with no mutation | `test_forged_expired_and_live_webhooks` |
| One processing of simultaneous duplicate events | `test_event_replay_and_concurrent_delivery`: 12 deliveries, exactly one processed and 11 duplicates |
| Payment failure -> 402, cancellation -> Free, stale events do not revive Pro | `test_payment_failure_cancellation_and_stale_event` |
| Upstream failures are retryable, not marked processed | `test_failed_sync_can_retry` |
| Unexpected price cannot upgrade a tenant | `test_wrong_price_does_not_upgrade` |
| Live API keys cannot create Checkout | `test_unconfigured_and_live_keys_fail_closed` |
| Durable monthly rollup, concurrent worker safety and tenant isolation | `test_rollup_idempotence_and_isolation` |
| Three retries, backoff, rollback and visible failure alert | `test_retry_failure_alert_and_rollback` |
| Recovery after worker crash and final-attempt crash alert | `test_worker_crash_recovery`; `test_last_attempt_crash_alert` |
| Concurrent startup migrations | `test_concurrent_migrations` |

The Stripe tests verify official SDK signatures over locally signed fixtures.
They do not prove real account Checkout or Stripe-origin event delivery.

## Pending real-account proof

- Real Stripe test Checkout and updated Pro limits.
- Genuine CLI webhook delivery and genuine test-event replay.
- Fresh-clone account-dependent setup.

Follow STRIPE_SETUP.md and paste sanitized real results here. This file deliberately
does not mark the whole capstone complete.
