"""Black-box smoke test using Python standard library only."""
import json
import os
import urllib.request

BASE = os.getenv("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")
KEY = os.getenv("DEMO_API_KEY", "blitz-demo-key")


def request(method, path, body=None, auth=True):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["X-API-Key"] = KEY
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=10) as response:
        return response.status, json.load(response)


def main():
    assert request("GET", "/healthz", auth=False)[1]["status"] == "ok"
    assert request("GET", "/.well-known/ucp", auth=False)[1]["ucp"]["version"] == "2026-08-25"
    products = request("POST", "/ucp/v1/catalog/search", {"query": "lavanda"})[1]["products"]
    assert len(products) == 1 and products[0]["id"] == "OLEO-001"
    status, cart = request("POST", "/ucp/v1/carts", {"line_items": [{"item": {"id": "OLEO-001"}, "quantity": 2}]})
    assert status == 201 and cart["totals"][-1]["amount"] == 9180
    assert request("GET", "/ucp/v1/carts/" + cart["id"])[1]["id"] == cart["id"]
    assert request("GET", "/api/usage")[1]["events"]["cart_created"] >= 1
    print("PASS: health, discovery, catalog, cart, get cart, metering")


if __name__ == "__main__":
    main()
