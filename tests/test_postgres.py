"""Real PostgreSQL integration, exercised by GitHub Actions postgres service.
Skip locally if no PostgreSQL service is configured.
"""
import os
import secrets

import pytest

pytestmark = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='Requires TEST_DATABASE_URL PostgreSQL instance')


def test_postgres_end_to_end(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from app.storage import connect
    monkeypatch.setenv('DATABASE_URL', os.environ['TEST_DATABASE_URL'])
    monkeypatch.setattr(main, 'DEMO_MODE', True)
    monkeypatch.setattr(main, 'SEED_KEY', 'blitz-postgres-test-key')
    with TestClient(main.app) as api:
        auth = {'X-API-Key': 'blitz-postgres-test-key'}
        lookup = api.post('/ucp/v1/catalog/lookup', json={'ids': ['OLEO-001']}, headers=auth)
        assert lookup.status_code == 200, lookup.text
        assert len(lookup.json()['products']) == 1
        key = 'ci_' + secrets.token_hex(12)
        order = {'line_items': [{'item': {'id': 'OLEO-001'}, 'quantity': 1}]}
        result = api.post('/ucp/v1/carts', headers={**auth, 'Idempotency-Key': key}, json=order)
        assert result.status_code == 201, result.text
        cart_id = result.json()['id']
        again = api.post('/ucp/v1/carts', headers={**auth, 'Idempotency-Key': key}, json=order)
        assert again.json()['id'] == cart_id
        assert api.get('/ucp/v1/carts/' + cart_id, headers=auth).status_code == 200
        assert api.get('/api/usage', headers=auth).json()['events']['cart_created'] >= 1
    monkeypatch.delenv('DATABASE_URL', raising=False)


def test_postgres_migration_idempotency(monkeypatch):
    from app.storage import connect, init_postgres_schema
    monkeypatch.setenv('DATABASE_URL', os.environ['TEST_DATABASE_URL'])
    with connect() as db:
        init_postgres_schema(db)
        init_postgres_schema(db)
        tables = db.execute("SELECT count(*) AS count FROM information_schema.tables WHERE table_schema='public' AND table_name='tenants'").fetchone()
        assert tables['count'] == 1
    monkeypatch.delenv('DATABASE_URL', raising=False)
