import json
from pathlib import Path
import pytest
from app.storage import to_postgres_sql
from scripts.fetch_ucp_contracts import verify_url, discover_refs


def test_postgres_sql_translation():
    assert to_postgres_sql('BEGIN IMMEDIATE') == 'BEGIN'
    assert to_postgres_sql('SELECT * FROM products WHERE tenant_id=? AND sku=?') == 'SELECT * FROM products WHERE tenant_id=%s AND sku=%s'
    assert to_postgres_sql('COMMIT') == 'COMMIT'


def test_version_pinned_contract_allowlist():
    assert verify_url('https://ucp.dev/2026-08-25/schemas/shopping/cart.json') == 'schemas/shopping/cart.json'
    for url in [
        'http://ucp.dev/2026-08-25/schemas/ucp.json',
        'https://evil.test/2026-08-25/schemas/ucp.json',
        'https://ucp.dev/2026-09-25/schemas/ucp.json',
        'https://ucp.dev/2026-08-25/../secrets',
        'https://ucp.dev/2026-08-25/schemas/ucp.json?q=1',
    ]:
        with pytest.raises(ValueError):
            verify_url(url)


def test_contract_ref_discovery():
    data = {'a': [{'$ref': 'https://ucp.dev/2026-08-25/schemas/ucp.json#/$defs/status'}]}
    assert list(discover_refs(data)) == ['https://ucp.dev/2026-08-25/schemas/ucp.json']


def test_postgres_schema_contains_tenant_keys_and_transactions():
    text = (Path(__file__).resolve().parents[1] / 'migrations/postgres/001_initial.sql').read_text()
    for table in ('tenants', 'platform_bindings', 'products', 'carts', 'checkouts', 'events', 'idempotency', 'signature_nonces'):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in text
    assert 'PRIMARY KEY (tenant_id, sku)' in text
    assert 'PRIMARY KEY (tenant_id, key)' in text


def test_contract_lock_absent_explicitly_fails():
    from scripts.fetch_ucp_contracts import OUTPUT
    if not (OUTPUT / 'manifest.json').exists():
        from scripts.fetch_ucp_contracts import verify
        with pytest.raises(SystemExit, match='Missing official schema lock'):
            verify()
