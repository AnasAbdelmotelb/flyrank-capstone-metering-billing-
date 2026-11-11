import argparse
import secrets

from app.db import connection, migrate
from app.service import hash_key


def seed(path=None, rotate_keys=False):
    migrate(path)
    with connection(path) as db:
        db.execute('BEGIN IMMEDIATE')
        for tenant_id, plan in [('demo-free', 'free'), ('demo-pro', 'pro')]:
            if db.execute('SELECT 1 FROM tenants WHERE id=?', (tenant_id,)).fetchone():
                if rotate_keys:
                    key = secrets.token_urlsafe(32)
                    db.execute('UPDATE tenants SET api_key_hash=? WHERE id=?', (hash_key(key), tenant_id))
                    print(f'{tenant_id} new API key (save locally): {key}')
                    continue
                print(f'{tenant_id}: already exists; API key unchanged')
                continue
            key = secrets.token_urlsafe(32)
            db.execute('INSERT INTO tenants VALUES (?,?)', (tenant_id, hash_key(key)))
            db.execute('INSERT INTO subscriptions VALUES (?,?,?)', (tenant_id, plan, 'active'))
            # The credential is shown once to its owner, never logged by the API.
            print(f'{tenant_id} API key (save locally): {key}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--rotate-keys', action='store_true', help='Replace demo API keys without changing usage')
    seed(rotate_keys=parser.parse_args().rotate_keys)
