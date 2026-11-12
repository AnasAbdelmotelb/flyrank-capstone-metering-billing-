"""Stripe test-only gateway and transactional subscription synchronization."""
import os
import time

import stripe

from app.db import connection
from app.service import BillingError, hash_key

SUPPORTED_EVENTS = {'checkout.session.completed', 'customer.subscription.created',
                    'customer.subscription.updated', 'customer.subscription.deleted'}


class StripeGateway:
    def __init__(self):
        self.price = os.getenv('STRIPE_PRO_PRICE_ID', '')
        self.secret = os.getenv('STRIPE_WEBHOOK_SECRET', '')
        self.key = os.getenv('STRIPE_SECRET_KEY', '')

    def client(self):
        if not self.key.startswith(('sk_test_', 'rk_test_', 'rkcs_test_')) or not self.price.startswith('price_'):
            raise BillingError(503, 'Configure Stripe test key and Pro price locally')
        return stripe.StripeClient(self.key, max_network_retries=0,
                                   http_client=stripe.RequestsClient(timeout=8))

    def checkout(self, tenant, attempt):
        base = os.getenv('APP_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
        try:
            return self.client().v1.checkout.sessions.create({
                'mode': 'subscription', 'client_reference_id': tenant,
                'subscription_data': {'metadata': {'tenant_id': tenant}},
                'line_items': [{'price': self.price, 'quantity': 1}],
                'success_url': base + '/billing/return?result=success',
                'cancel_url': base + '/billing/return?result=canceled',
            }, options={'idempotency_key': 'checkout-' + hash_key(f'{tenant}:{attempt}')}).to_dict()
        except stripe.StripeError:
            raise BillingError(502, 'Stripe unavailable; retry Checkout later') from None

    def retrieve(self, subscription_id):
        try:
            return self.client().v1.subscriptions.retrieve(subscription_id).to_dict()
        except stripe.StripeError:
            raise BillingError(502, 'Stripe subscription lookup failed; retry event') from None

    def verify(self, payload, signature):
        if not self.secret.startswith('whsec_'):
            raise BillingError(503, 'Configure Stripe webhook signing secret locally')
        try:
            return stripe.Webhook.construct_event(payload, signature, self.secret).to_dict()
        except (ValueError, KeyError, TypeError, stripe.SignatureVerificationError):
            raise BillingError(400, 'Invalid webhook payload or signature') from None


class Payments:
    def __init__(self, path=None, gateway=None):
        self.path, self.gateway = path, gateway or StripeGateway()

    def checkout(self, tenant):
        with connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT 1 FROM stripe_links WHERE tenant_id=? AND stripe_status NOT IN ('canceled','incomplete_expired')", (tenant,)).fetchone()
            if active:
                raise BillingError(409, 'Tenant already has a Stripe subscription; manage it in Stripe test dashboard')
            old = db.execute('SELECT * FROM checkout_sessions WHERE tenant_id=?', (tenant,)).fetchone()
            if old and old['expires_at'] > int(time.time()):
                return {'session_id': old['session_id'], 'url': old['url']}
            # Stable attempt across a network failure; a new attempt after known expiry.
            attempt = old['session_id'] if old else 'initial'
            session = self.gateway.checkout(tenant, attempt)
            if session.get('livemode') is not False:
                raise BillingError(400, 'Live Stripe objects are forbidden')
            db.execute('INSERT OR REPLACE INTO checkout_sessions VALUES (?,?,?,?)',
                       (tenant, session['id'], session['url'], session['expires_at']))
            return {'session_id': session['id'], 'url': session['url']}

    def webhook(self, payload, signature):
        event = self.gateway.verify(payload, signature)
        if event.get('livemode') is not False:
            raise BillingError(400, 'Live Stripe events are forbidden')
        if not isinstance(event.get('id'), str) or not isinstance(event.get('type'), str):
            raise BillingError(400, 'Malformed Stripe event')
        with connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM stripe_events WHERE id=?', (event['id'],)).fetchone():
                return {'status': 'duplicate'}
            if event['type'] not in SUPPORTED_EVENTS:
                return {'status': 'ignored'}
            obj = event.get('data', {}).get('object', {})
            if not isinstance(obj, dict):
                raise BillingError(400, 'Malformed Stripe object')
            sub_id = obj.get('subscription') if event['type'] == 'checkout.session.completed' else obj.get('id')
            if not isinstance(sub_id, str) or not sub_id.startswith('sub_'):
                raise BillingError(400, 'Missing subscription ID')
            # Retrieve current Stripe state inside the write lock. Out-of-order events
            # cannot overwrite the mirror with stale event snapshots.
            sub = self.gateway.retrieve(sub_id)
            if sub.get('livemode') is not False:
                raise BillingError(400, 'Live Stripe subscriptions are forbidden')
            tenant = sub.get('metadata', {}).get('tenant_id')
            if not tenant or not db.execute('SELECT 1 FROM tenants WHERE id=?', (tenant,)).fetchone():
                return {'status': 'ignored'}
            if event['type'] == 'checkout.session.completed' and obj.get('client_reference_id') != tenant:
                raise BillingError(400, 'Checkout tenant mismatch')
            items = sub.get('items', {}).get('data', [])
            if len(items) != 1 or items[0].get('price', {}).get('id') != self.gateway.price or items[0].get('quantity') != 1:
                raise BillingError(400, 'Unsupported subscription price or quantity')
            existing = db.execute('SELECT tenant_id FROM stripe_links WHERE subscription_id=?', (sub_id,)).fetchone()
            if existing and existing['tenant_id'] != tenant:
                raise BillingError(400, 'Subscription tenant mismatch')
            status = sub['status']
            other = db.execute("SELECT 1 FROM stripe_links WHERE tenant_id=? AND subscription_id<>? AND stripe_status NOT IN ('canceled','incomplete_expired')", (tenant, sub_id)).fetchone()
            if other and status not in ('canceled', 'incomplete_expired'):
                raise BillingError(409, 'Multiple subscriptions require operator reconciliation')
            # A late canceled subscription must not downgrade a newer active one.
            db.execute('INSERT OR REPLACE INTO stripe_links VALUES (?,?,?,?)',
                       (sub_id, tenant, sub['customer'], status))
            if other:
                db.execute('INSERT INTO stripe_events(id,type) VALUES (?,?)', (event['id'], event['type']))
                return {'status': 'processed'}
            if status in ('canceled', 'incomplete_expired'):
                plan, local_status = 'free', 'active'
            else:
                plan, local_status = 'pro', 'active' if status in ('active', 'trialing') else 'unpaid'
            db.execute('UPDATE subscriptions SET plan_id=?, status=? WHERE tenant_id=?',
                       (plan, local_status, tenant))
            db.execute('INSERT INTO stripe_events(id,type) VALUES (?,?)', (event['id'], event['type']))
            return {'status': 'processed'}
