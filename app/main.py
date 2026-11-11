import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import connection, migrate
from app.models import TokenUsage
from app.service import BillingError, MeterService
from app.payments import Payments


def create_app(path=None, clock=None, gateway=None):
    service = MeterService(path, clock)
    payments = Payments(path, gateway)

    @asynccontextmanager
    async def lifespan(app):
        migrate(path)
        yield

    app = FastAPI(title='LLM Usage Metering & Billing Service', lifespan=lifespan)
    bearer = HTTPBearer(auto_error=False)

    def tenant(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if credentials is None:
            raise BillingError(401, 'Bearer API key required', {'WWW-Authenticate': 'Bearer'})
        return service.authenticate(credentials.credentials)

    @app.exception_handler(BillingError)
    async def billing_error(request: Request, exc: BillingError):
        return JSONResponse({'detail': exc.message}, status_code=exc.status, headers=exc.headers)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request: Request, exc: sqlite3.OperationalError):
        if 'locked' not in str(exc).lower():
            raise exc
        return JSONResponse({'detail': 'Database busy; retry with the same idempotency key'},
                            status_code=503, headers={'Retry-After': '1'})

    @app.get('/health')
    def health():
        with connection(path) as db:
            db.execute('SELECT 1 FROM plans LIMIT 1').fetchone()
        return {'status': 'ok'}

    @app.post('/generate')
    def generate(usage: TokenUsage, tenant_id: Annotated[str, Depends(tenant)],
                 idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r'^\S+$')]):
        return service.record(tenant_id, idempotency_key, usage)

    @app.get('/usage')
    def usage(tenant_id: Annotated[str, Depends(tenant)]):
        return service.usage(tenant_id)

    @app.post('/billing/checkout')
    def checkout(tenant_id: Annotated[str, Depends(tenant)]):
        return payments.checkout(tenant_id)

    @app.post('/webhooks/stripe')
    async def stripe_webhook(request: Request):
        from starlette.concurrency import run_in_threadpool
        # Check streamed bytes, not just the untrusted Content-Length header.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                raise BillingError(413, 'Webhook payload too large')
        return await run_in_threadpool(payments.webhook, bytes(body), request.headers.get('stripe-signature', ''))

    @app.get('/billing/return')
    def checkout_return():
        return {'message': 'Checkout finished. Your plan updates only after a verified Stripe webhook; check GET /usage.'}

    @app.get('/jobs/alerts')
    def alerts(tenant_id: Annotated[str, Depends(tenant)]):
        with connection(path) as db:
            rows = db.execute('''SELECT a.job_id,a.message,a.created_at FROM job_alerts a
                JOIN jobs j ON j.id=a.job_id WHERE j.tenant_id=?''', (tenant_id,)).fetchall()
        return {'alerts': [dict(row) for row in rows]}

    @app.get('/usage/history')
    def history(tenant_id: Annotated[str, Depends(tenant)]):
        with connection(path) as db:
            rows = db.execute('''SELECT month,api_calls,ai_tokens,cost_microusd FROM monthly_rollups
                WHERE tenant_id=? ORDER BY month DESC LIMIT 24''', (tenant_id,)).fetchall()
        return {'months': [dict(row) for row in rows]}

    return app


app = create_app()
