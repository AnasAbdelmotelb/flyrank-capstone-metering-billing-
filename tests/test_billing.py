from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db import connection, migrate
from app.main import create_app
from app.models import TokenUsage
from app.pricing import calculate_cost
from app.service import BillingError, MeterService, hash_key


@pytest.fixture
def setup(tmp_path):
    path = str(tmp_path / 'test.db')
    migrate(path)
    with connection(path) as db:
        for name in ('a', 'b'):
            db.execute('INSERT INTO tenants VALUES (?,?)', (name, hash_key(name)))
            db.execute('INSERT INTO subscriptions VALUES (?, ?, ?)', (name, 'free', 'active'))
    return path


def test_retry_and_conflict(setup):
    with TestClient(create_app(setup)) as client:
        headers = {'Authorization': 'Bearer a', 'Idempotency-Key': 'retry'}
        first = client.post('/generate', headers=headers, json={'input_tokens': 20})
        second = client.post('/generate', headers=headers, json={'input_tokens': 20})
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert client.post('/generate', headers=headers, json={'input_tokens': 21}).status_code == 409
        assert client.get('/usage', headers=headers).json()['used']['api_calls'] == 1


def test_concurrent_retries(setup):
    service = MeterService(setup)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: service.record('a', 'same', TokenUsage()), range(20)))
    assert len({r['event_id'] for r in results}) == 1
    assert service.usage('a')['used']['api_calls'] == 1


def test_concurrent_quota_boundary(setup):
    with connection(setup) as db:
        db.execute("UPDATE plans SET api_limit=1 WHERE id='free'")
    service = MeterService(setup)

    def attempt(i):
        try:
            service.record('a', str(i), TokenUsage())
            return 200
        except BillingError as exc:
            return exc.status

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(12)))
    assert statuses.count(200) == 1
    assert statuses.count(429) == 11
    assert service.usage('a')['used']['api_calls'] == 1


def test_token_limit_and_retry_after(setup):
    with TestClient(create_app(setup)) as client:
        headers = {'Authorization': 'Bearer a', 'Idempotency-Key': 'boundary'}
        assert client.post('/generate', headers=headers, json={'input_tokens': 100000}).status_code == 200
        headers['Idempotency-Key'] = 'over'
        response = client.post('/generate', headers=headers, json={'input_tokens': 1})
        assert response.status_code == 429
        assert int(response.headers['Retry-After']) > 0
        assert client.get('/usage', headers=headers).json()['used']['ai_tokens'] == 100000


def test_pricing_and_rollup(setup):
    usage = TokenUsage(input_tokens=1000, cached_input_tokens=400,
                       output_tokens=500, reasoning_tokens=200)
    # 1000 call + 600*2 fresh + 400*1 cached + 500*8 output = 6600.
    assert calculate_cost(usage) == 6600
    service = MeterService(setup)
    service.record('a', 'pricing', usage)
    assert service.usage('a')['used'] == {'api_calls': 1, 'ai_tokens': 1500, 'cost_microusd': 6600}


def test_auth_isolation_and_inactive_subscription(setup):
    with TestClient(create_app(setup)) as client:
        assert client.get('/usage').status_code == 401
        assert client.get('/usage', headers={'Authorization': 'Bearer unknown'}).status_code == 401
        for name in ('a', 'b'):
            response = client.post('/generate', json={}, headers={
                'Authorization': f'Bearer {name}', 'Idempotency-Key': 'shared'})
            assert response.status_code == 200
        with connection(setup) as db:
            db.execute("UPDATE subscriptions SET status='unpaid' WHERE tenant_id='a'")
        response = client.post('/generate', json={}, headers={
            'Authorization': 'Bearer a', 'Idempotency-Key': 'new'})
        assert response.status_code == 402
        assert client.get('/usage', headers={'Authorization': 'Bearer b'}).json()['used']['api_calls'] == 1


@pytest.mark.parametrize('payload', [
    {'input_tokens': -1}, {'input_tokens': 1.5}, {'input_tokens': True},
    {'input_tokens': '5'}, {'cached_input_tokens': 1}, {'reasoning_tokens': 1}, {'extra': 1},
])
def test_bad_input(setup, payload):
    with TestClient(create_app(setup)) as client:
        response = client.post('/generate', json=payload, headers={
            'Authorization': 'Bearer a', 'Idempotency-Key': 'invalid'})
        assert response.status_code == 422
    assert MeterService(setup).usage('a')['used']['api_calls'] == 0


def test_utc_month_reset_and_old_retry(setup):
    now = [datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)]
    service = MeterService(setup, clock=lambda: now[0])
    old = service.record('a', 'old', TokenUsage(input_tokens=100000))
    now[0] = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert service.usage('a')['used']['api_calls'] == 0
    assert service.record('a', 'old', TokenUsage(input_tokens=100000)) == old
    service.record('a', 'new', TokenUsage(input_tokens=100000))
    assert service.usage('a')['used']['api_calls'] == 1


def test_persistence(setup):
    MeterService(setup).record('a', 'persist', TokenUsage())
    migrate(setup)
    assert MeterService(setup).usage('a')['used']['api_calls'] == 1
