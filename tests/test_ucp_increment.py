import hashlib
from app import main


def test_profile_advertises_only_supported_capabilities(client):
    profile=client.get('/.well-known/ucp').json()
    assert set(profile)=={'ucp', 'keys'}
    assert 'dev.ucp.shopping.cart' in profile['ucp']['capabilities']
    assert 'dev.ucp.shopping.checkout' not in profile['ucp']['capabilities']


def test_agent_profile_binding(client,headers):
    trusted={**headers,'UCP-Agent':'profile="https://agent.example/profiles/demo.json"'}
    assert client.post('/ucp/v1/catalog/search',json={},headers=trusted).status_code==200
    unknown={**headers,'UCP-Agent':'profile="https://attacker.example/x"'}
    assert client.post('/ucp/v1/catalog/search',json={},headers=unknown).status_code==403
    malformed={**headers,'UCP-Agent':'http://example.com'}
    assert client.post('/ucp/v1/catalog/search',json={},headers=malformed).status_code==400
    fake={**headers,'UCP-Agent':'profile="http://localhost/profile"'}
    assert client.post('/ucp/v1/catalog/search',json={},headers=fake).status_code==400


def test_production_requires_ucp_agent(client,headers,monkeypatch):
    monkeypatch.setattr(main,'DEMO_MODE',False)
    assert client.post('/ucp/v1/catalog/search',json={},headers=headers).status_code==400
    trusted={**headers,'UCP-Agent':'profile="https://agent.example/profiles/demo.json"'}
    assert client.post('/ucp/v1/catalog/search',json={},headers=trusted).status_code==200


def test_search_cursor_page_and_tamper_detection(client,headers):
    r=client.post('/ucp/v1/catalog/search',json={'pagination':{'limit':1}},headers=headers)
    assert r.status_code==200
    data=r.json()
    assert data['pagination']['has_next_page']
    token=data['pagination']['cursor']
    r2=client.post('/ucp/v1/catalog/search',json={'pagination':{'limit':1,'cursor':token}},headers=headers)
    assert r2.status_code==200
    assert r2.json()['products'][0]['id']!=data['products'][0]['id']
    assert client.post('/ucp/v1/catalog/search',json={'query':'oleo','pagination':{'cursor':token}},headers=headers).status_code==400
    fake=token[:-1]+('A' if token[-1]!='A' else 'B')
    assert client.post('/ucp/v1/catalog/search',json={'pagination':{'cursor':fake}},headers=headers).status_code==400


def test_catalog_detail_and_missing(client,headers):
    a=client.post('/ucp/v1/catalog/product',json={'id':'OLEO-001'},headers=headers)
    assert a.status_code==200 and a.json()['product']['id']=='OLEO-001'
    missing=client.post('/ucp/v1/catalog/product',json={'id':'invalid'},headers=headers).json()
    assert missing['ucp']['status']=='error'
    lookup=client.post('/ucp/v1/catalog/lookup',json={'ids':['invalid','OLEO-001']},headers=headers).json()
    assert lookup['products'][0]['id']=='OLEO-001'
    assert lookup['messages'][0]['code']=='not_found'


def test_experimental_checkout_lifecycle_cannot_charge(client,headers):
    body={'line_items':[{'item':{'id':'OLEO-001'},'quantity':2}]}
    created=client.post('/ucp/v1/checkout-sessions',json=body,headers=headers)
    assert created.status_code==201
    data=created.json()
    assert data['status']=='requires_escalation'
    assert data['messages'][0]['severity']=='requires_buyer_review'
    assert data['totals'][-1]['amount']==9180
    url='/ucp/v1/checkout-sessions/'+data['id']
    assert client.get(url,headers=headers).status_code==200
    assert client.post(url+'/complete',headers=headers).status_code==501
    updated=client.put(url,json={'line_items':[{'item':{'id':'OLEO-001'},'quantity':1}]},headers=headers)
    assert updated.json()['totals'][-1]['amount']==4590
    assert client.post(url+'/cancel',headers=headers).json()['status']=='cancelled'
    assert client.put(url,json=body,headers=headers).status_code==409
    assert client.post('/ucp/v1/checkout-sessions',json={**body,'buyer':{'email':'a@b.com'}},headers=headers).status_code==422


def test_checkout_tenant_boundary(client,headers):
    body={'line_items':[{'item':{'id':'OLEO-001'},'quantity':1}]}
    cid=client.post('/ucp/v1/checkout-sessions',json=body,headers=headers).json()['id']
    with main.conn() as db:
        db.execute('INSERT INTO tenants VALUES (?,?,?,?,?)',('different','diff','Different',hashlib.sha256(b'diff').hexdigest(),'https://example.com'))
    assert client.get('/ucp/v1/checkout-sessions/'+cid,headers={'X-API-Key':'diff'}).status_code==404


def test_non_demo_checkout_disabled(client,headers,monkeypatch):
    monkeypatch.setattr(main,'DEMO_MODE',False)
    bound={**headers,'UCP-Agent':'profile="https://agent.example/profiles/demo.json"'}
    body={'line_items':[{'item':{'id':'OLEO-001'},'quantity':1}]}
    assert client.post('/ucp/v1/checkout-sessions',json=body,headers=bound).status_code==501
    assert client.get('/ucp/v1/checkout-sessions/chk_any',headers=bound).status_code==501


def test_malformed_cursor_never_500(client,headers):
    r=client.post('/ucp/v1/catalog/search',json={'pagination':{'cursor':'!!!'}},headers=headers)
    assert r.status_code==400
