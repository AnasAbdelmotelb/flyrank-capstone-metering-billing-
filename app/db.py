import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connection(path=None):
    db = sqlite3.connect(path or os.getenv('DATABASE_PATH', 'billing.db'), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def migrate(path=None):
    with connection(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)')
        folder = Path(__file__).resolve().parent.parent / 'migrations'
        for file in sorted(folder.glob('*.sql')):
            if not db.execute('SELECT 1 FROM schema_migrations WHERE name=?', (file.name,)).fetchone():
                # Explicit transaction includes both DDL and migration marker.
                script = "BEGIN IMMEDIATE;\n" + file.read_text()
                db.executescript(script)
                db.execute('INSERT INTO schema_migrations VALUES (?)', (file.name,))
                db.commit()
