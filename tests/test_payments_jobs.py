import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import connection, migrate
from app.main import create_app
from app.models import TokenUsage
from app.payments import Payments, StripeGateway
from app.service import BillingError, MeterService, hash_key
from app.worker import enqueue, run_once


@pytest.fixture
def database(tmp_path):
    path = str(tmp_path / 'billing.db')
    migrate(path)
    with connection(path) as db:
        for name in ('a', 'b'):
            db.execute('INSERT INTO tenants VALUES (?,?)', (name, hash_key(name)))
            db.execute('INSERT INTO subscriptions VALUES (?,?,?)', (name, 'free', 'active'))
    return path


class FakeGateway(StripeGateway):
    """Only network calls are replaced; webhook signature verification is real."""
    price = 'price_fixture'
    secret = 'whsec_fixture_only'

    def __init__(self):
        self.calls = 0
        self.sub = {'id': 'sub_fixture', 'livemode': False, 'customer': 'cus_fixture',
                    'status': 'active', 'metadata': {'tenant_id': 'a'},
                    'items': {'data': [{'price': {'id': self.price}, 'quantity': 1}]}}

    def checkout(self, tenant, attempt):
        self.calls += 1
        return {'id': 'cs_test_fixture', 'url': 'https://checkout.stripe.com/test-fixture',
                'expires_at': int(time.time()) + 1000, 'livemode': False}

    def retrieve(self, subscription_id):
        return self.sub


def event(kind='customer.subscription.updated', event_id='evt_fixture'):
    obj = {'id': 'sub_fixture'}
    if kind == 'checkout.session.completed':
        obj = {'id': 'cs_test_fixture', 'subscription': 'sub_fixture', 'client_reference_id': 'a'}
    return {'id': event_id, 'object': 'event', 'livemode': False,
            'type': kind, 'data': {'object': obj}}


def signed(payload, secret=FakeGateway.secret, timestamp=None):
    body = json.dumps(payload).encode()
    stamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), str(stamp).encode() + b'.' + body, hashlib.sha256).hexdigest()
    return body, f't={stamp},v1={digest}'


def deliver(client, payload, **kwargs):
    body, sig = signed(payload, **kwargs)
    return client.post('/webhooks/stripe', content=body, headers={'Stripe-Signature': sig})


def test_checkout_auth_and_reuse(database):
    gateway = FakeGateway()
    with TestClient(create_app(database, gateway=gateway)) as client:
        assert client.post('/billing/checkout').status_code == 401
        headers = {'Authorization': 'Bearer a'}
        first = client.post('/billing/checkout', headers=headers)
        assert first.status_code == 200
        assert client.post('/billing/checkout', headers=headers).json() == first.json()
        assert gateway.calls == 1
        assert MeterService(database).usage('a')['plan'] == 'free'
        assert deliver(client, event('checkout.session.completed')).status_code == 200
        assert client.post('/billing/checkout', headers=headers).status_code == 409
        assert client.get('/usage', headers=headers).json()['limits']['api_calls'] == 10000


def test_forged_expired_and_live_webhooks(database):
    with TestClient(create_app(database, gateway=FakeGateway())) as client:
        assert deliver(client, event(), secret='wrong').status_code == 400
        assert deliver(client, event(), timestamp=int(time.time()) - 600).status_code == 400
        payload = event()
        payload['livemode'] = True
        assert deliver(client, payload).status_code == 400
        assert MeterService(database).usage('a')['plan'] == 'free'
        with connection(database) as db:
            assert db.execute('SELECT COUNT(*) FROM stripe_events').fetchone()[0] == 0


def test_event_replay_and_concurrent_delivery(database):
    payments = Payments(database, FakeGateway())
    body, sig = signed(event())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: payments.webhook(body, sig), range(12)))
    assert sum(r['status'] == 'processed' for r in results) == 1
    assert sum(r['status'] == 'duplicate' for r in results) == 11
    with connection(database) as db:
        assert db.execute('SELECT COUNT(*) FROM stripe_events').fetchone()[0] == 1


def test_payment_failure_cancellation_and_stale_event(database):
    gateway = FakeGateway()
    with TestClient(create_app(database, gateway=gateway)) as client:
        assert deliver(client, event()).status_code == 200
        gateway.sub['status'] = 'past_due'
        assert deliver(client, event(event_id='evt_unpaid')).status_code == 200
        response = client.post('/generate', json={}, headers={'Authorization': 'Bearer a', 'Idempotency-Key': 'unpaid'})
        assert response.status_code == 402
        gateway.sub['status'] = 'canceled'
        assert deliver(client, event('customer.subscription.deleted', 'evt_cancel')).status_code == 200
        assert MeterService(database).usage('a')['plan'] == 'free'
        # A stale active snapshot cannot revive a canceled canonical subscription.
        payload = event(event_id='evt_late')
        payload['data']['object']['status'] = 'active'
        assert deliver(client, payload).status_code == 200
        assert MeterService(database).usage('a')['plan'] == 'free'
        assert MeterService(database).usage('b')['plan'] == 'free'


def test_failed_sync_can_retry(database):
    gateway = FakeGateway()
    original = gateway.retrieve
    gateway.retrieve = lambda _: (_ for _ in ()).throw(BillingError(502, 'temporary failure'))
    with TestClient(create_app(database, gateway=gateway)) as client:
        assert deliver(client, event()).status_code == 502
        gateway.retrieve = original
        assert deliver(client, event()).json()['status'] == 'processed'


def test_wrong_price_does_not_upgrade(database):
    gateway = FakeGateway()
    gateway.sub['items']['data'][0]['price']['id'] = 'price_other'
    with TestClient(create_app(database, gateway=gateway)) as client:
        assert deliver(client, event()).status_code == 400
        assert MeterService(database).usage('a')['plan'] == 'free'


def test_unconfigured_and_live_keys_fail_closed(database, monkeypatch):
    monkeypatch.setenv('STRIPE_SECRET_KEY', 'sk_live_forbidden_fixture')
    monkeypatch.setenv('STRIPE_PRO_PRICE_ID', 'price_fixture')
    gateway = StripeGateway()
    with TestClient(create_app(database, gateway=gateway)) as client:
        assert client.post('/billing/checkout', headers={'Authorization': 'Bearer a'}).status_code == 503


@pytest.mark.parametrize('prefix', ['sk_test_', 'rk_test_', 'rkcs_test_'])
def test_supported_test_key_formats(monkeypatch, prefix):
    monkeypatch.setenv('STRIPE_SECRET_KEY', prefix + 'fixture_only')
    monkeypatch.setenv('STRIPE_PRO_PRICE_ID', 'price_fixture')
    assert StripeGateway().client() is not None


def test_rollup_idempotence_and_isolation(database):
    clock = lambda: datetime(2026, 10, 10, tzinfo=timezone.utc)
    MeterService(database, clock).record('a', 'rollup', TokenUsage(input_tokens=100))
    now = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())
    enqueue(database, now)
    enqueue(database, now)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: run_once(database, now), range(8)))
    with connection(database) as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0] == 2
    with TestClient(create_app(database)) as client:
        history = client.get('/usage/history', headers={'Authorization': 'Bearer a'}).json()['months']
        assert history == [{'month': '2026-10', 'api_calls': 1, 'ai_tokens': 100, 'cost_microusd': 1200}]
        other = client.get('/usage/history', headers={'Authorization': 'Bearer b'}).json()['months']
        assert other[0]['api_calls'] == 0


def test_retry_failure_alert_and_rollback(database):
    with connection(database) as db:
        db.execute("INSERT INTO jobs(tenant_id,month) VALUES ('a','2026-10')")

    def fail(db, job):
        db.execute("INSERT INTO monthly_rollups VALUES ('a','2026-10',1,1,1)")
        raise RuntimeError('fixture failure')

    assert run_once(database, 100, fail)
    assert not run_once(database, 101, fail)  # Backoff is respected.
    assert run_once(database, 102, fail)
    assert run_once(database, 106, fail)
    with connection(database) as db:
        assert db.execute('SELECT COUNT(*) FROM monthly_rollups').fetchone()[0] == 0
        job = db.execute('SELECT * FROM jobs').fetchone()
        assert job['status'] == 'failed' and job['attempts'] == 3
    with TestClient(create_app(database)) as client:
        assert len(client.get('/jobs/alerts', headers={'Authorization': 'Bearer a'}).json()['alerts']) == 1
        assert client.get('/jobs/alerts', headers={'Authorization': 'Bearer b'}).json()['alerts'] == []


def test_worker_crash_recovery(database):
    with connection(database) as db:
        db.execute("INSERT INTO jobs(tenant_id,month,status,attempts,lease_token,lease_until) VALUES ('a','2026-10','running',1,'dead',100)")
    assert not run_once(database, 99)
    assert run_once(database, 100)
    with connection(database) as db:
        assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'done'


def test_last_attempt_crash_alert(database):
    with connection(database) as db:
        db.execute("INSERT INTO jobs(tenant_id,month,status,attempts,lease_token,lease_until) VALUES ('a','2026-10','running',3,'dead',100)")
    assert not run_once(database, 100)
    with connection(database) as db:
        assert db.execute('SELECT COUNT(*) FROM job_alerts').fetchone()[0] == 1


def test_concurrent_migrations(tmp_path):
    path = str(tmp_path / 'migrations.db')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: migrate(path), range(8)))
    with connection(path) as db:
        assert db.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0] == 2
