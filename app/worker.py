"""Durable, leased jobs for closed-month usage summaries; run separately from HTTP."""
import argparse
import logging
import time
import uuid
from datetime import datetime, timezone

from app.db import connection, migrate
from app.service import totals

MAX_ATTEMPTS = 3
LEASE_SECONDS = 60
logger = logging.getLogger(__name__)


def enqueue(path=None, now=None):
    date = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    previous = date.replace(day=1).date().toordinal() - 1
    month = date.fromordinal(previous).strftime('%Y-%m')
    with connection(path) as db:
        # Include all historically used closed months, plus last month for idle tenants.
        db.execute('''INSERT OR IGNORE INTO jobs(tenant_id,month)
            SELECT tenant_id,month FROM usage_events WHERE month < ?''', (date.strftime('%Y-%m'),))
        db.execute('INSERT OR IGNORE INTO jobs(tenant_id,month) SELECT id,? FROM tenants', (month,))


def rollup(db, job):
    used = totals(db, job['tenant_id'], job['month'])
    db.execute('INSERT OR REPLACE INTO monthly_rollups VALUES (?,?,?,?,?)', (
        job['tenant_id'], job['month'], used['api_calls'], used['ai_tokens'], used['cost_microusd']))


def run_once(path=None, now=None, processor=rollup):
    now = int(time.time() if now is None else now)
    token = uuid.uuid4().hex
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE')
        # A crashed final attempt becomes a durable failure after lease expiration.
        expired = db.execute("SELECT id FROM jobs WHERE status='running' AND lease_until<=? AND attempts>=?", (now, MAX_ATTEMPTS)).fetchall()
        for row in expired:
            db.execute("UPDATE jobs SET status='failed', lease_token=NULL WHERE id=?", (row['id'],))
            db.execute('INSERT OR IGNORE INTO job_alerts(job_id,message) VALUES (?,?)',
                       (row['id'], 'Monthly rollup failed after worker lease expired'))
            logger.error('Monthly rollup job %s failed after lease expiration', row['id'])
        job = db.execute('''SELECT * FROM jobs WHERE attempts<? AND
            ((status='pending' AND available_at<=?) OR (status='running' AND lease_until<=?))
            ORDER BY id LIMIT 1''', (MAX_ATTEMPTS, now, now)).fetchone()
        if job is None:
            return False
        job = dict(job)
        job['attempts'] += 1
        db.execute("UPDATE jobs SET status='running', attempts=?, lease_token=?, lease_until=? WHERE id=?",
                   (job['attempts'], token, now + LEASE_SECONDS, job['id']))
    try:
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            owned = db.execute("SELECT 1 FROM jobs WHERE id=? AND status='running' AND lease_token=?", (job['id'], token)).fetchone()
            if not owned:
                return True
            processor(db, job)
            db.execute("UPDATE jobs SET status='done',lease_token=NULL,lease_until=NULL WHERE id=?", (job['id'],))
    except Exception:
        # No exception text: failures may contain secrets from future integrations.
        with connection(path) as db:
            db.execute('BEGIN IMMEDIATE')
            owned = db.execute('SELECT 1 FROM jobs WHERE id=? AND lease_token=?', (job['id'], token)).fetchone()
            if owned:
                failed = job['attempts'] >= MAX_ATTEMPTS
                db.execute('UPDATE jobs SET status=?,available_at=?,lease_token=NULL,lease_until=NULL WHERE id=?',
                           ('failed' if failed else 'pending', now + 2 ** job['attempts'], job['id']))
                if failed:
                    db.execute('INSERT OR IGNORE INTO job_alerts(job_id,message) VALUES (?,?)',
                               (job['id'], 'Monthly rollup failed after 3 attempts; operator review required'))
                    logger.error('Monthly rollup job %s failed after 3 attempts', job['id'])
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Schedule and drain currently ready jobs, then exit')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    migrate()
    while True:
        enqueue()
        while run_once():
            pass
        if args.once:
            return
        time.sleep(2)


if __name__ == '__main__':
    main()
