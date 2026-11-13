"""Reviewable, version-pinned fetch of official UCP JSON schemas and OpenAPI.

Never fetch during API requests. Offline hash validation is available without network.
The resolver accepts ONLY HTTPS ucp.dev paths under the requested version.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urldefrag, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

VERSION = '2026-08-25'
ROOT = f'https://ucp.dev/{VERSION}/'
PATHS = [
 'services/shopping/rest.openapi.json',
 'schemas/ucp.json',
 'schemas/shopping/cart.json',
 'schemas/shopping/checkout.json',
 'schemas/shopping/catalog_search.json',
 'schemas/shopping/catalog_lookup.json',
]
OUTPUT = Path(__file__).resolve().parents[1] / 'contracts' / VERSION
MAX_BYTES = 3_000_000
MAX_ARTIFACTS = 120

class RefusedRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirect rejected')


def verify_url(url: str) -> str:
    parts = urlsplit(urldefrag(url)[0])
    if (parts.scheme != 'https' or parts.netloc != 'ucp.dev' or
        parts.query or parts.username or parts.password or
        not parts.path.startswith(f'/{VERSION}/') or '..' in parts.path.split('/')):
        raise ValueError(f'Unapproved UCP document URL: {url}')
    return parts.path[len(f'/{VERSION}/'):]


def fetch(url: str) -> bytes:
    verify_url(url)
    import urllib.request
    opener = build_opener(RefusedRedirect())
    with opener.open(Request(url, headers={'User-Agent': 'Blitz-UCP-Contract-Lock/0.4'}), timeout=15) as response:
        if response.geturl() != url:
            raise ValueError('Redirect rejected')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Document exceeds 3 MB limit')
    json.loads(raw)
    return raw


def discover_refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == '$ref' and isinstance(item, str) and item.startswith('https://'):
                yield urldefrag(item)[0]
            else:
                yield from discover_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from discover_refs(item)


def sync():
    pending = {ROOT + p for p in PATHS}
    downloaded = {}
    while pending:
        if len(downloaded) + len(pending) > MAX_ARTIFACTS:
            raise ValueError('Exceeded maximum contract graph size')
        url = sorted(pending).pop(0)
        pending.remove(url)
        if url in downloaded:
            continue
        path = verify_url(url)
        raw = fetch(url)
        parsed = json.loads(raw)
        downloaded[url] = raw
        for ref in discover_refs(parsed):
            verify_url(ref)
            if ref not in downloaded:
                pending.add(ref)
        print('Fetched', path)
    # Write only after full reference graph has been fetched successfully.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for url, raw in downloaded.items():
        path = verify_url(url)
        destination = OUTPUT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        artifacts[path] = {'url': url, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    (OUTPUT / 'manifest.json').write_text(json.dumps({'version': VERSION, 'artifacts': dict(sorted(artifacts.items()))}, indent=2) + '\n')


def verify():
    manifest = OUTPUT / 'manifest.json'
    if not manifest.exists():
        raise SystemExit('Missing official schema lock; run python scripts/fetch_ucp_contracts.py --sync from a trusted network')
    data = json.loads(manifest.read_text())
    if data['version'] != VERSION or not set(PATHS).issubset(data['artifacts']):
        raise ValueError('Manifest missing version or required documents')
    for path, meta in data['artifacts'].items():
        if verify_url(meta['url']) != path:
            raise ValueError('Unsafe manifest URL')
        raw = (OUTPUT / path).read_bytes()
        if len(raw) != meta['bytes'] or hashlib.sha256(raw).hexdigest() != meta['sha256']:
            raise ValueError('Contract integrity mismatch: ' + path)
        parsed = json.loads(raw)
        for ref in discover_refs(parsed):
            if verify_url(ref) not in data['artifacts']:
                raise ValueError(f'Unpinned schema dependency: {ref}')
    return data

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--sync', action='store_true')
    actions.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    sync() if args.sync else print(f'LOCK VERIFIED: {len(verify()["artifacts"])} official documents')
