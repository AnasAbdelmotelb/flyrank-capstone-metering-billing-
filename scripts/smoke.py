"""Exercise the live localhost service with an isolated temporary tenant."""
import json
import secrets
import urllib.request
import uuid

from app.db import connection
from app.service import hash_key

key, tenant = secrets.token_urlsafe(32), 'smoke-' + uuid.uuid4().hex
with connection() as db:
    db.execute('INSERT INTO tenants VALUES (?,?)', (tenant, hash_key(key)))
    db.execute('INSERT INTO subscriptions VALUES (?,?,?)', (tenant, 'free', 'active'))
try:
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
               'Idempotency-Key': 'live-smoke'}
    body = json.dumps({'input_tokens': 1000, 'cached_input_tokens': 400,
                       'output_tokens': 500, 'reasoning_tokens': 200}).encode()
    request = urllib.request.Request('http://127.0.0.1:8000/generate', data=body, headers=headers)
    first = json.load(urllib.request.urlopen(request, timeout=5))
    second = json.load(urllib.request.urlopen(request, timeout=5))
    assert first == second
    request = urllib.request.Request('http://127.0.0.1:8000/usage', headers=headers)
    usage = json.load(urllib.request.urlopen(request, timeout=5))
    assert usage['used'] == {'api_calls': 1, 'ai_tokens': 1500, 'cost_microusd': 6600}
    print('Live HTTP smoke passed: identical retry, one call, 1500 tokens, 6600 micro-USD')
finally:
    with connection() as db:
        db.execute('DELETE FROM usage_events WHERE tenant_id=?', (tenant,))
        db.execute('DELETE FROM subscriptions WHERE tenant_id=?', (tenant,))
        db.execute('DELETE FROM tenants WHERE id=?', (tenant,))
