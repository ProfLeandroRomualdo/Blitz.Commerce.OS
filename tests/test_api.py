import hashlib
import json
from app import main


def test_health_and_profile(client):
    assert client.get("/healthz").json()["status"] == "ok"
    body = client.get("/.well-known/ucp").json()
    assert body["ucp"]["version"] == "2026-08-25"
    assert body["ucp"]["payment_handlers"] == {}
    assert "checkout" not in str(body["ucp"]["capabilities"])


def test_missing_and_bad_auth(client):
    assert client.post("/ucp/v1/catalog/search", json={}).status_code == 401
    assert client.post("/ucp/v1/catalog/search", json={}, headers={"X-API-Key":"wrong"}).status_code == 401


def test_catalog_search_lookup_and_meter(client, headers):
    r = client.post("/ucp/v1/catalog/search", json={"query":"cambio"}, headers=headers)
    assert r.status_code == 200
    assert len(r.json()["products"]) == 1
    assert r.json()["products"][0]["price_range"]["min"]["amount"] == 12990
    r = client.post("/ucp/v1/catalog/lookup", json={"ids":["OLEO-001","MISSING"]}, headers=headers)
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["products"]] == ["OLEO-001"]
    usage = client.get("/api/usage",headers=headers).json()["events"]
    assert usage == {"catalog_lookup":1,"catalog_search":1}


def test_create_cart_prices_stock_and_handoff(client, headers):
    r=client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":"CAMBIO-001"},"quantity":2}]},headers=headers)
    assert r.status_code == 201
    data=r.json()
    assert data["totals"][-1]["amount"] == 25980
    assert "checkout" not in data["continue_url"]
    assert client.get(data["continue_url"].replace("http://localhost:8000","" )).status_code == 200
    assert client.get("/ucp/v1/carts/"+data["id"],headers=headers).status_code == 200
    assert client.post("/ucp/v1/carts/"+data["id"]+"/cancel",headers=headers).status_code == 200
    assert client.get(data["continue_url"].replace("http://localhost:8000","" )).status_code == 404


def test_no_stock_no_unknown_no_overlimit(client, headers):
    for sku,qty,status in [("FILTRO-001",1,409),("NOPE",1,422),("CAMBIO-001",101,422)]:
        response=client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":sku},"quantity":qty}]},headers=headers)
        assert response.status_code == status


def test_idempotency_replay_conflict(client,headers):
    h={**headers,"Idempotency-Key":"key_test_123456"}
    a=client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":"OLEO-001"},"quantity":1}]},headers=h)
    b=client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":"OLEO-001"},"quantity":1}]},headers=h)
    assert a.json()["id"] == b.json()["id"]
    assert client.get("/api/usage",headers=headers).json()["events"]["cart_created"] == 1
    c=client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":"OLEO-001"},"quantity":2}]},headers=h)
    assert c.status_code == 409


def test_cross_tenant_isolation(client,headers):
    cart=client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":"OLEO-001"},"quantity":1}]},headers=headers).json()
    with main.conn() as db:
        db.execute("INSERT INTO tenants VALUES(?,?,?,?,?)",("other","other","Other",hashlib.sha256(b"other-secret").hexdigest(),"https://example.com/checkout"))
        db.execute("INSERT INTO products VALUES(?,?,?,?,?,?)",("other","OTHER","Other product","Private",999,2))
    other={"X-API-Key":"other-secret"}
    assert client.get("/ucp/v1/carts/"+cart["id"],headers=other).status_code == 404
    assert client.post("/ucp/v1/catalog/search",json={"query":""},headers=other).json()["products"][0]["id"] == "OTHER"
    assert client.post("/ucp/v1/catalog/lookup",json={"ids":["OLEO-001"]},headers=other).json()["products"] == []
    assert client.get("/api/usage",headers=other).json()["events"] == {"catalog_lookup":1,"catalog_search":1}


def test_validation(client,headers):
    assert client.post("/ucp/v1/catalog/search",json={"pagination":{"limit":99999}},headers=headers).status_code == 422
    assert client.post("/ucp/v1/carts",json={"line_items":[]},headers=headers).status_code == 422
    assert client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":"OLEO-001"},"quantity":1}]},headers={**headers,"Idempotency-Key":"bad"}).status_code == 422


def test_concurrent_duplicate_sku_cannot_bypass_stock(client,headers):
    assert client.post("/ucp/v1/carts",json={"line_items":[{"item":{"id":"CAMBIO-001"},"quantity":5},{"item":{"id":"CAMBIO-001"},"quantity":5}]},headers=headers).status_code == 409


def test_update_cart_and_cancel_protection(client, headers):
    base={"line_items":[{"item":{"id":"OLEO-001"},"quantity":1}]}
    cart=client.post("/ucp/v1/carts",json=base,headers=headers).json()
    newer={"line_items":[{"item":{"id":"OLEO-001"},"quantity":3}]}
    response=client.put("/ucp/v1/carts/"+cart["id"],json=newer,headers=headers)
    assert response.status_code == 200
    assert response.json()["totals"][-1]["amount"] == 13770
    client.post("/ucp/v1/carts/"+cart["id"]+"/cancel",headers=headers)
    assert client.put("/ucp/v1/carts/"+cart["id"],json=base,headers=headers).status_code == 409


def test_search_wildcard_literal(client, headers):
    assert client.post("/ucp/v1/catalog/search",json={"query":"%"},headers=headers).json()["products"] == []
    assert client.post("/ucp/v1/catalog/search",json={"query":"_"},headers=headers).json()["products"] == []
