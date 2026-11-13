"""Database access: SQLite demo and PostgreSQL production-compatible SQL layer.

Postgres requires psycopg[binary]; no implicit switch from postgres to SQLite.
Query placeholders use ? internally and are converted into psycopg's %s safely.
Never interpolate untrusted identifiers into SQL.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def is_postgres() -> bool:
    return os.getenv('DATABASE_URL', '').startswith(('postgresql://', 'postgres://'))


def to_postgres_sql(sql: str) -> str:
    """Translate the fixed internal SQL dialect, including SQLite BEGIN IMMEDIATE.

    Query text is authored by developers; all user values remain bound params.
    """
    if sql.strip().upper() == 'BEGIN IMMEDIATE':
        return 'BEGIN'
    # Only SQL from fixed internal statements is accepted. Our existing queries
    # contain no question marks inside SQL string literals.
    return sql.replace('?', '%s')


class PostgresConnection:
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def execute(self, sql, params=()):
        return self.wrapped.execute(to_postgres_sql(sql), params)

    def executemany(self, sql, values):
        with self.wrapped.cursor() as cur:
            cur.executemany(to_postgres_sql(sql), values)

    def close(self):
        self.wrapped.close()


@contextmanager
def connect():
    url = os.getenv('DATABASE_URL', '')
    if url:
        if not is_postgres():
            raise RuntimeError('DATABASE_URL must start with postgresql:// or postgres://')
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError('Install PostgreSQL extra: pip install -r requirements-postgres.txt') from exc
        # Explicit BEGIN/COMMIT in cart/checkout handlers; otherwise individual
        # statements autocommit just as existing SQLite behavior does.
        db = psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=8)
        try:
            yield PostgresConnection(db)
        finally:
            db.close()
    else:
        path = Path(os.getenv('DATABASE_PATH', './blitz.db'))
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
        finally:
            db.close()


def init_postgres_schema(db):
    sql_path = Path(__file__).resolve().parents[1] / 'migrations' / 'postgres' / '001_initial.sql'
    # Migrations are fixed and versioned. Never execute migration contents from
    # untrusted data, application request bodies, or dynamically fetched URLs.
    statements = [part.strip() for part in sql_path.read_text().split(';') if part.strip()]
    db.execute('BEGIN')
    try:
        for sql in statements:
            db.execute(sql)
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise
