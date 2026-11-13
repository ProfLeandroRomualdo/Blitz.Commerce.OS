"""Strict, deliberately bounded subset of UCP REST request authentication.

Supports one RFC 9421 signature labelled sig1, Ed25519 JWK, no WBA, and
pre-approved, locally pinned platform profiles only. No remote URL fetch.
Unsupported structures fail closed. NOT a full RFC 9421 implementation.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from cryptography.exceptions import InvalidSignature

PROTOCOL = '2026-08-25'
CAPS = ('dev.ucp.shopping.catalog.search', 'dev.ucp.shopping.catalog.lookup', 'dev.ucp.shopping.cart')


class UCPError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


def profile_url(header: str | None) -> str:
    m = re.fullmatch(r'profile="(https://[^"\s]+)"', header or '')
    if not m:
        raise UCPError(400, 'invalid_profile_url', 'Expected UCP-Agent: profile="https://..."')
    url = m.group(1)
    p = urlsplit(url)
    try:
        valid = len(url) <= 2048 and bool(p.netloc) and not p.username and not p.password and not p.fragment and p.port in (None, 443)
    except ValueError:
        valid = False
    if not valid:
        raise UCPError(400, 'invalid_profile_url', 'Invalid agent profile URL')
    return url


def load_profiles(path: str) -> dict:
    """Operator-reviewed profile snapshots. File should be read-only at runtime."""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict) or len(data) > 1000:
        raise ValueError('Expected profile URL -> profile JSON mapping (<=1000)')
    for url, profile in data.items():
        if profile_url(f'profile="{url}"') != url or not isinstance(profile, dict):
            raise ValueError('Malformed pinned profile')
        if not isinstance(profile.get('keys', []), list) or len(profile.get('keys', [])) > 32:
            raise ValueError('Malformed keys')
    return data


def negotiate(platform_profile: dict, business_capabilities: tuple[str, ...] = CAPS) -> dict:
    meta = platform_profile.get('ucp')
    if not isinstance(meta, dict):
        raise UCPError(422, 'profile_malformed', 'Missing ucp block')
    if meta.get('version') != PROTOCOL:
        raise UCPError(422, 'version_unsupported', 'Unsupported UCP protocol version')
    platform = meta.get('capabilities', {})
    if not isinstance(platform, dict):
        raise UCPError(422, 'profile_malformed', 'Malformed capability map')
    common = {}
    for cap in business_capabilities:
        entries = platform.get(cap, [])
        if not isinstance(entries, list):
            raise UCPError(422, 'profile_malformed', 'Malformed capability versions')
        versions = {item['version'] for item in entries if isinstance(item, dict) and isinstance(item.get('version'), str)}
        if PROTOCOL in versions:
            common[cap] = [{'version': PROTOCOL}]
    return common


def _b64d(s: str) -> bytes:
    return base64.b64decode(s, validate=True)


def digest(raw: bytes) -> str:
    return 'sha-256=:' + base64.b64encode(hashlib.sha256(raw).digest()).decode('ascii') + ':'


def _components_and_params(value: str):
    # One signature, one label, well-defined subset of structured fields.
    m = re.fullmatch(r'(sig1)=\(([^)]*)\)((?:;[a-z]+=(?:"[^"\\]*"|[0-9]+))*)', value or '')
    if not m:
        raise UCPError(401, 'signature_invalid', 'Unsupported Signature-Input structure')
    comp_raw, suffix = m.group(2), m.group(3)
    parts = re.findall(r'"([a-z@-]+)"', comp_raw)
    if not parts or ' '.join(f'"{p}"' for p in parts) != comp_raw or len(parts) != len(set(parts)):
        raise UCPError(401, 'signature_invalid', 'Malformed or repeated covered components')
    param_parts = re.findall(r';([a-z]+)=("[^"\\]*"|[0-9]+)', suffix)
    if ''.join(';' + k + '=' + v for k,v in param_parts) != suffix:
        raise UCPError(401, 'signature_invalid', 'Malformed signature parameters')
    params = dict(param_parts)
    if len(params) != len(param_parts):
        raise UCPError(401, 'signature_invalid', 'Duplicate signature parameter')
    return parts, params, f'({comp_raw}){suffix}'


def signature_base(method: str, authority: str, path: str, query: str, headers: dict, parts: list[str], sigparams: str) -> bytes:
    values = {'@method': method.upper(), '@authority': authority.lower(), '@path': path, '@query': '?' + query}
    lines = []
    for part in parts:
        if part.startswith('@'):
            if part not in values:
                raise UCPError(401, 'signature_invalid', 'Unsupported derived component')
            value = values[part]
        else:
            value = headers.get(part)
            if value is None or '\n' in value or '\r' in value:
                raise UCPError(401, 'signature_invalid', 'Missing/invalid covered HTTP field')
            value = value.strip()
        lines.append(f'"{part}": {value}')
    lines.append(f'"@signature-params": {sigparams}')
    return '\n'.join(lines).encode('utf-8')


def verify_request(method: str, authority: str, path: str, query: str, headers: dict, body: bytes, profile: dict,
                   now: int | None = None) -> str:
    """Verify a signed request against pinned profile keys; return authenticated kid.

    This subset requires timestamps and nonce even where base UCP permits omission.
    Anti-replay storage is handled by the ASGI middleware, not this function.
    """
    now = int(time.time()) if now is None else now
    inp, sig = headers.get('signature-input'), headers.get('signature')
    if not inp or not sig:
        raise UCPError(401, 'signature_missing', 'Signature headers required')
    parts, params, sigparams = _components_and_params(inp)
    required = {'@method', '@authority', '@path', 'ucp-agent'}
    if query:
        required.add('@query')
    if body:
        required.update(('content-digest', 'content-type'))
        if not hmac.compare_digest(headers.get('content-digest', ''), digest(body)):
            raise UCPError(400, 'digest_mismatch', 'Body digest mismatch')
    if method.upper() in ('POST', 'PUT', 'PATCH', 'DELETE'):
        required.add('idempotency-key')
        if not headers.get('idempotency-key'):
            raise UCPError(400, 'signature_invalid', 'Idempotency-Key missing')
    if headers.get('signature-agent'):
        # Avoid incorrectly accepting the WBA dictionary-member selection shape.
        raise UCPError(400, 'algorithm_unsupported', 'WBA shape not yet supported')
    if not required.issubset(parts):
        raise UCPError(401, 'signature_invalid', 'Mandatory components not covered')
    try:
        created = int(params['created'])
        expires = int(params['expires'])
    except (ValueError, KeyError):
        raise UCPError(401, 'signature_invalid', 'created and expires required')
    if created > now + 30 or expires < now or expires <= created or expires - created > 300:
        raise UCPError(401, 'signature_invalid', 'Signature timestamp outside permitted window')
    nonce = params.get('nonce','').strip('"')
    if not (12 <= len(nonce) <= 256 and re.fullmatch(r'[A-Za-z0-9_-]+', nonce)):
        raise UCPError(401, 'signature_invalid', 'Unique nonce required')
    kid = params.get('keyid', '').strip('"')
    if not kid:
        raise UCPError(401, 'key_not_found', 'Missing keyid')
    keys = profile.get('keys', [])
    matching = [k for k in keys if k.get('kid') == kid and k.get('use', 'sig') == 'sig' and 'verify' in k.get('key_ops', ['verify'])]
    if not matching:
        raise UCPError(401, 'key_not_found', 'Key not found in pinned profile')
    k = matching[0]
    if k.get('kty') != 'OKP' or k.get('crv') != 'Ed25519' or k.get('alg', 'EdDSA') != 'EdDSA':
        raise UCPError(400, 'algorithm_unsupported', 'Only Ed25519 supported')
    m = re.fullmatch(r'sig1=:([A-Za-z0-9+/=]+):', sig or '')
    if not m:
        raise UCPError(401, 'signature_invalid', 'Malformed signature')
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(k['x'] + '=' * (-len(k['x']) % 4)))
        raw_sig = _b64d(m.group(1))
        pub.verify(raw_sig, signature_base(method, authority, path, query, headers, parts, sigparams))
    except (InvalidSignature, ValueError, KeyError, TypeError):
        raise UCPError(401, 'signature_invalid', 'Signature verification failed')
    return kid + ':' + nonce


def sign_request(method: str, authority: str, path: str, query: str, headers: dict, body: bytes,
                 private_key: Ed25519PrivateKey, kid: str, created: int, nonce: str) -> dict:
    """Reference fixture signer, useful for tests and client integration examples."""
    h = {k.lower(): v for k, v in headers.items()}
    parts = ['@method', '@authority', '@path']
    if query:
        parts.append('@query')
    if h.get('ucp-agent'):
        parts.append('ucp-agent')
    if h.get('idempotency-key'):
        parts.append('idempotency-key')
    if body:
        h['content-digest'] = digest(body)
        parts.extend(['content-digest', 'content-type'])
    quoted = ' '.join('"' + p + '"' for p in parts)
    sigparams = f'({quoted});created={created};expires={created+180};nonce="{nonce}";keyid="{kid}"'
    signature = private_key.sign(signature_base(method, authority, path, query, h, parts, sigparams))
    h['signature-input'] = 'sig1=' + sigparams
    h['signature'] = 'sig1=:' + base64.b64encode(signature).decode() + ':'
    return h


def jwk_from_private(private_key: Ed25519PrivateKey) -> dict:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    x = base64.urlsafe_b64encode(private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).rstrip(b'=').decode()
    canonical = json.dumps({'crv':'Ed25519','kty':'OKP','x':x}, separators=(',', ':'), sort_keys=True).encode()
    kid = base64.urlsafe_b64encode(hashlib.sha256(canonical).digest()).rstrip(b'=').decode()
    return {'kty':'OKP', 'crv':'Ed25519', 'alg':'EdDSA', 'x':x, 'kid':kid, 'use':'sig', 'key_ops':['verify']}


def response_signature(status: int, body: bytes, content_type: str, private_key: Ed25519PrivateKey, now: int) -> dict:
    jwk = jwk_from_private(private_key)
    headers = {'content-type':content_type}
    parts = ['@status']
    if body:
        headers['content-digest'] = digest(body)
        parts.extend(('content-digest', 'content-type'))
    sigparams = '(' + ' '.join('"' + p + '"' for p in parts) + f');created={now};keyid="{jwk["kid"]}"'
    lines = []
    for part in parts:
        val = str(status) if part == '@status' else headers[part]
        lines.append(f'"{part}": {val}')
    lines.append(f'"@signature-params": {sigparams}')
    signature = private_key.sign('\n'.join(lines).encode())
    headers['signature-input'] = 'sig1=' + sigparams
    headers['signature'] = 'sig1=:' + base64.b64encode(signature).decode() + ':'
    return headers
