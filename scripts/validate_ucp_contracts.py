"""Offline conformance diagnostic against pinned upstream schemas.

The program deliberately returns a nonzero exit code on mismatches. It never
marks the service conformant based on internal Pydantic validation alone.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from scripts.fetch_ucp_contracts import OUTPUT, ROOT, verify


def load_registry():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    manifest = verify()
    registry = Registry()
    for path, entry in manifest['artifacts'].items():
        if not path.endswith('.json'):
            continue
        schema = json.loads((OUTPUT / path).read_text())
        if path.startswith('schemas/'):
            Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(entry['url'], Resource(contents=schema, specification=DRAFT202012))
    return registry


def validate_payload(schema_path: str, pointer: str, payload: dict):
    from jsonschema import Draft202012Validator, FormatChecker
    registry = load_registry()
    uri = ROOT + schema_path
    schema = {'$ref': uri + pointer}
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    return sorted(validator.iter_errors(payload), key=lambda e: str(e.path))


def diagnose_demo():
    from fastapi.testclient import TestClient
    from app import main
    findings = []
    tests = [
        ('POST', '/ucp/v1/catalog/search', {'query': 'oleo'}, 'schemas/shopping/catalog_search.json', '#/$defs/search_response'),
        ('POST', '/ucp/v1/catalog/lookup', {'ids': ['OLEO-001']}, 'schemas/shopping/catalog_lookup.json', '#/$defs/lookup_response'),
        ('POST', '/ucp/v1/carts', {'line_items': [{'item': {'id': 'OLEO-001'}, 'quantity': 1}]}, 'schemas/shopping/cart.json', ''),
    ]
    with TestClient(main.app) as client:
        for method, path, body, schema_path, pointer in tests:
            response = client.request(method, path, headers={'X-API-Key': main.SEED_KEY}, json=body)
            if response.status_code >= 400:
                findings.append({'path': path, 'error': f'HTTP {response.status_code}: {response.text[:300]}'})
                continue
            for issue in validate_payload(schema_path, pointer, response.json()):
                findings.append({'path': path, 'field': '/'.join(map(str, issue.absolute_path)), 'error': issue.message[:250]})
    return findings

if __name__ == '__main__':
    try:
        findings = diagnose_demo()
    except Exception as exc:
        print(f'CONTRACT CHECK INCOMPLETE: {exc}', file=sys.stderr)
        sys.exit(2)
    report = {'contract_version': '2026-08-25', 'outcome': 'FAIL' if findings else 'PASS_SELECTED_RESPONSES_ONLY', 'findings': findings}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(1 if findings else 0)
