import hashlib
import json
import uuid
from datetime import datetime, timezone

from app.db import connection
from app.pricing import PRICING_VERSION, calculate_cost


class BillingError(Exception):
    def __init__(self, status, message, headers=None):
        self.status, self.message, self.headers = status, message, headers


def hash_key(value):
    return hashlib.sha256(value.encode()).hexdigest()


def subscription(db, tenant):
    row = db.execute('''SELECT s.status, p.* FROM subscriptions s
        JOIN plans p ON p.id=s.plan_id WHERE s.tenant_id=?''', (tenant,)).fetchone()
    if row is None:
        raise BillingError(402, 'A subscription is required')
    return row


def totals(db, tenant, month):
    row = db.execute('''SELECT COALESCE(SUM(api_calls),0) api_calls,
        COALESCE(SUM(tokens),0) ai_tokens, COALESCE(SUM(cost_microusd),0) cost_microusd
        FROM usage_events WHERE tenant_id=? AND month=?''', (tenant, month)).fetchone()
    return dict(row)


class MeterService:
    def __init__(self, path=None, clock=None):
        self.path = path
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def authenticate(self, key):
        with connection(self.path) as db:
            row = db.execute('SELECT id FROM tenants WHERE api_key_hash=?', (hash_key(key),)).fetchone()
            if row is None:
                raise BillingError(401, 'Invalid API key', {'WWW-Authenticate': 'Bearer'})
            return row['id']

    def record(self, tenant, key, usage):
        fingerprint = hash_key(usage.model_dump_json())
        with connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('''SELECT fingerprint, response FROM usage_events
                WHERE tenant_id=? AND idempotency_key=?''', (tenant, key)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise BillingError(409, 'Idempotency key was used with a different request')
                return json.loads(old['response'])
            now = self.clock()
            month = now.strftime('%Y-%m')
            plan = subscription(db, tenant)
            if plan['status'] != 'active':
                raise BillingError(402, 'Subscription inactive; payment or upgrade required')
            used = totals(db, tenant, month)
            tokens = usage.input_tokens + usage.output_tokens
            if used['api_calls'] + 1 > plan['api_limit'] or used['ai_tokens'] + tokens > plan['token_limit']:
                next_month = now.replace(year=now.year + (now.month == 12), month=now.month % 12 + 1,
                                         day=1, hour=0, minute=0, second=0, microsecond=0)
                raise BillingError(429, 'Monthly usage quota exceeded; wait for reset or upgrade',
                                   {'Retry-After': str(max(1, int((next_month - now).total_seconds())))})
            result = {'event_id': str(uuid.uuid4()), 'result': 'Simulated generation complete',
                      'month': month, 'api_calls': 1, 'ai_tokens': tokens,
                      'cost_microusd': calculate_cost(usage), 'pricing_version': PRICING_VERSION}
            db.execute('''INSERT INTO usage_events VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (
                result['event_id'], tenant, month, now.isoformat(), key, fingerprint, 1,
                tokens, result['cost_microusd'], PRICING_VERSION, json.dumps(result)
            ))
            return result

    def usage(self, tenant):
        with connection(self.path) as db:
            # Keep plan and totals in one read snapshot.
            db.execute('BEGIN')
            plan = subscription(db, tenant)
            month = self.clock().strftime('%Y-%m')
            return {'month': month, 'plan': plan['id'], 'status': plan['status'],
                    'used': totals(db, tenant, month),
                    'limits': {'api_calls': plan['api_limit'], 'ai_tokens': plan['token_limit']},
                    'currency': 'USD', 'money_unit': 'micro-dollar'}
