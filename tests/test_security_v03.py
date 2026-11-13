import base64
import json
import secrets
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.ucp_security import (UCPError, jwk_from_private, negotiate, sign_request,
                              verify_request, response_signature)

URL = 'https://agent.example/profiles/demo.json'
CAPS = {'dev.ucp.shopping.catalog.search': [{'version': '2026-08-25'}],
        'dev.ucp.shopping.cart': [{'version': '2026-08-25'}]}

@pytest.fixture
def agent():
    key = Ed25519PrivateKey.generate()
    return key, {'ucp': {'version': '2026-08-25', 'services': {},
                        'payment_handlers': {}, 'capabilities': CAPS},
                 'keys': [jwk_from_private(key)]}


def signed(key, payload=b'{"query":"oil"}', path='/ucp/v1/catalog/search', nonce=None):
    headers = {'ucp-agent': f'profile="{URL}"', 'idempotency-key': 'req-1',
               'content-type':'application/json'}
    return sign_request('POST', 'testserver', path, '', headers, payload, key,
                        jwk_from_private(key)['kid'], int(time.time()), nonce or secrets.token_urlsafe(28))


def test_negotiation_exact_version_and_unknown(agent):
    _, profile = agent
    assert set(negotiate(profile)) == set(CAPS)
    profile['ucp']['capabilities']['dev.ucp.shopping.cart'] = [{'version':'2026-01-23'}]
    assert 'dev.ucp.shopping.cart' not in negotiate(profile)
    profile['ucp']['version'] = '2026-01-23'
    with pytest.raises(UCPError, match='Unsupported UCP'):
        negotiate(profile)


def test_verify_ed25519_and_mutations(agent):
    key, profile = agent
    body = b'{"query":"oil"}'
    headers = signed(key, body)
    assert verify_request('POST','testserver','/ucp/v1/catalog/search','',headers,body,profile)
    for kwargs in [dict(path='/ucp/v1/catalog/lookup'), dict(authority='attacker.example'),dict(body=b'{"query":"hacked"}')]:
        args=dict(method='POST',authority='testserver',path='/ucp/v1/catalog/search',query='',headers=headers,body=body,profile=profile)
        args.update(kwargs)
        with pytest.raises(UCPError): verify_request(**args)
    bad = dict(headers)
    bad['signature-input'] = bad['signature-input'].replace('"@authority" ', '')
    with pytest.raises(UCPError): verify_request('POST','testserver','/ucp/v1/catalog/search','',bad,body,profile)
    bad = dict(headers)
    bad['signature'] = bad['signature'][:-4] + 'AAA:'
    with pytest.raises(UCPError): verify_request('POST','testserver','/ucp/v1/catalog/search','',bad,body,profile)


def test_response_signature(agent):
    key,_ = agent
    h = response_signature(201,b'{"ok":true}', 'application/json',key,int(time.time()))
    assert h['content-digest'].startswith('sha-256=:')
    assert '"@status"' in h['signature-input']


def test_gateway_strict_signed_requests(client, headers, agent, tmp_path, monkeypatch):
    from app import main
    key, profile = agent
    file = tmp_path / 'profiles.json'
    file.write_text(json.dumps({URL:profile}))
    monkeypatch.setattr(main,'STRICT_UCP',True)
    monkeypatch.setattr(main,'PINNED_PROFILES_FILE',str(file))
    merchant_key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(main,'business_signing_key',lambda: merchant_key)
    body = b'{"query":"oleo"}'
    h = {**headers, **signed(key,body)}
    r = client.post('/ucp/v1/catalog/search', content=body,headers=h)
    assert r.status_code == 200, r.text
    assert list(r.json()['ucp']['capabilities']) == ['dev.ucp.shopping.catalog.search']
    assert 'signature' in r.headers
    assert 'keys' in client.get('/.well-known/ucp').json()
    repeated = client.post('/ucp/v1/catalog/search',content=body,headers=h)
    assert repeated.status_code == 401
    assert repeated.json()['code'] == 'signature_invalid'
    mutated = client.post('/ucp/v1/catalog/search',content=b'{"query":"other"}',headers={**headers,**signed(key,body)})
    assert mutated.status_code == 400
    assert mutated.json()['code'] == 'digest_mismatch'
    missing = client.post('/ucp/v1/catalog/search',content=body,headers=headers)
    assert missing.status_code == 400
    assert missing.json()['code'] == 'invalid_profile_url'


def test_unpinned_profile_rejected(client,headers,agent,tmp_path,monkeypatch):
    from app import main
    key,_ = agent
    p=tmp_path/'p.json'
    p.write_text('{}')
    monkeypatch.setattr(main,'STRICT_UCP',True)
    monkeypatch.setattr(main,'PINNED_PROFILES_FILE',str(p))
    h={**headers, **signed(key)}
    r=client.post('/ucp/v1/catalog/search',content=b'{"query":"oil"}', headers=h)
    assert r.status_code == 424
    assert r.json()['code'] == 'profile_unreachable'


def test_negotiation_rejects_unavailable_operation(client,headers,agent,tmp_path,monkeypatch):
    from app import main
    key,profile=agent
    p=tmp_path/'p.json';p.write_text(json.dumps({URL:profile}))
    monkeypatch.setattr(main,'STRICT_UCP',True)
    monkeypatch.setattr(main,'PINNED_PROFILES_FILE',str(p))
    h={**headers,**signed(key,b'{"ids":["OLEO-001"]}',path='/ucp/v1/catalog/lookup')}
    r=client.post('/ucp/v1/catalog/lookup',content=b'{"ids":["OLEO-001"]}',headers=h)
    assert r.status_code == 200
    assert r.json()['messages'][0]['code']=='capabilities_incompatible'
