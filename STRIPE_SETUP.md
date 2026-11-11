# Stripe test verification before submission

Use a Stripe test environment only. Never enable live mode or provide a real card.
See [Stripe CLI installation](https://docs.stripe.com/cli/install),
[webhook testing](https://docs.stripe.com/webhooks), and
[subscription Checkout](https://docs.stripe.com/payments/checkout/build-subscriptions).

## 1. Configure the account locally

1. Sign in to Stripe and select a test environment/sandbox.
2. In the test product catalog create a product named Pro and one recurring
   monthly USD price (for example $10/month; this is separate from usage costs).
3. Copy the price ID, starting `price_`.
4. Copy `.env.example` to `.env` if `.env` does not already exist.
5. In `.env` set `STRIPE_SECRET_KEY` to your `sk_test_...` key and
   `STRIPE_PRO_PRICE_ID` to the recurring price ID. Keep these values local.
6. Install the official Stripe CLI. On macOS with Homebrew:
   `brew install stripe/stripe-cli/stripe`.

On the current development machine, an official checksum-verified arm64 binary
is available at `.tools/stripe` (ignored by Git). If `stripe` is not on PATH,
substitute `.tools/stripe` for `stripe` in the commands below. A fresh clone must
install the CLI separately using the official installation instructions.

## 2. Forward webhooks

In a separate terminal:

```bash
stripe login
stripe listen --events checkout.session.completed,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted --forward-to http://127.0.0.1:8000/webhooks/stripe
```

Complete browser authentication yourself. Copy the listener's `whsec_...` value
into `STRIPE_WEBHOOK_SECRET` in `.env`. It is distinct from the API key and from
any dashboard endpoint's signing secret. Keep the listener running.

Restart the app after changing `.env`:

```bash
.venv/bin/python -m app.seed
.venv/bin/python -m app.run
```

Save the Free tenant API key printed by seed. For existing demo tenants whose key
was lost, explicitly rotate with `.venv/bin/python -m app.seed --rotate-keys`.

## 3. Complete a real test Checkout

1. Open `http://127.0.0.1:8000/docs` and authorize using the Free tenant key.
2. Execute `GET /usage` and save its Free limits.
3. Execute `POST /billing/checkout`; open the returned `url` in your browser.
4. Complete Stripe Checkout with test card `4242 4242 4242 4242`, a future expiry,
   and any valid CVC. Supply test customer information only.
5. Wait for the CLI to show successful webhook delivery.
6. Execute `GET /usage`; it must show `plan: pro` and limits of 10000 calls and
   1000000 tokens. The return page alone is not proof of an upgrade.

## 4. Verify forgery and replay

Unsigned requests must return 400 when the webhook secret is configured:

```bash
curl -i http://127.0.0.1:8000/webhooks/stripe \
  -H 'Content-Type: application/json' -d '{}'
```

For a genuine test event replay through the local listener, use the helper below.
Find the completed Checkout event ID (`evt_...`) in Stripe's test Events view:

```bash
.venv/bin/python -m scripts.replay_stripe evt_REPLACE_LOCALLY
.venv/bin/python -m scripts.replay_stripe evt_REPLACE_LOCALLY
```

The helper retrieves the genuine event from your test account, signs it with the
local listener secret, then posts it to localhost. Both responses should report
`duplicate` if the CLI already delivered it. This is a locally signed replay of
a genuine Stripe event, not a new Stripe-origin delivery. The automated signature
and replay tests separately demonstrate one processing under concurrency.

Do not use a generic `stripe trigger` result as proof of a tenant upgrade:
fixture subscriptions lack this app's tenant metadata and configured price.

## 5. Cancellation and evidence

Cancel the test subscription immediately in the Stripe test dashboard. After the
webhook, `/usage` should return Free limits without resetting consumed usage.
An at-period-end cancellation retains Pro while the subscription is active.

Paste sanitized actual responses, event IDs, timestamps, and CLI 2xx delivery
lines into EVIDENCE.md. Never include API keys, API Authorization headers, webhook
secrets, or payment/customer personal details. Complete the live-checklist only
after observing results; fixtures do not replace this account-dependent proof.
