"""Blitz Commerce OS: a deliberately small, auditable commerce API prototype.

UCP REST-shaped catalog and cart endpoints; NOT yet certified UCP conformant.
No payment processing, no agent authentication federation, no live ERP integrations.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Annotated
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import Response as StarletteResponse
from app.storage import connect as conn, is_postgres, init_postgres_schema
from app.ucp_security import UCPError, load_profiles, profile_url, negotiate, verify_request, response_signature, jwk_from_private
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field

VERSION = "2026-08-25"
STRICT_UCP = os.getenv("STRICT_UCP", "false").lower() == "true"
PINNED_PROFILES_FILE = os.getenv("PINNED_PROFILES_FILE", "")
SIGNING_KEY_B64 = os.getenv("UCP_SIGNING_KEY_B64", "")

def business_signing_key():
    if not SIGNING_KEY_B64:
        return None
    return Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(SIGNING_KEY_B64 + "=" * (-len(SIGNING_KEY_B64) % 4)))
ACTIVE_CAPS = ContextVar("active_ucp_capabilities", default=None)
SPEC = f"https://ucp.dev/{VERSION}"
DB = os.getenv("DATABASE_PATH", "./blitz.db")  # backward-compatible test fixture; storage reads env dynamically
BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
SEED_KEY = os.getenv("DEMO_API_KEY", "blitz-demo-key")
if not DEMO_MODE and (not BASE_URL.startswith("https://") or SEED_KEY == "blitz-demo-key" or not is_postgres()):
    raise RuntimeError("Non-demo mode requires HTTPS PUBLIC_BASE_URL, PostgreSQL DATABASE_URL and a non-default DEMO_API_KEY")

@asynccontextmanager
async def lifespan(application):
    init_db()
    yield

app = FastAPI(title="Blitz Commerce OS MVP", version="0.4.1",
              description="Experimental UCP-aligned commerce API. Not UCP-certified.", lifespan=lifespan)

@app.middleware("http")
async def strict_ucp_gateway(request: Request, call_next):
    """Opt-in pinned identity, capability negotiation, RFC9421 Ed25519 subset.

    Signature verification runs before any UCP business handler or side effects.
    The optional strict mode is intended for offline interoperability experiments.
    """
    if not STRICT_UCP or not request.url.path.startswith("/ucp/v1/"):
        return await call_next(request)
    try:
        url = profile_url(request.headers.get("ucp-agent"))
        if not PINNED_PROFILES_FILE:
            raise UCPError(503, "profile_unreachable", "Pinned profiles not configured")
        profiles = load_profiles(PINNED_PROFILES_FILE)
        if url not in profiles:
            raise UCPError(424, "profile_unreachable", "Profile not in reviewed allowlist")
        caps = negotiate(profiles[url])
        root = "dev.ucp.shopping.cart" if request.url.path.startswith("/ucp/v1/carts") else (
            "dev.ucp.shopping.catalog.lookup" if request.url.path.endswith(("/lookup", "/product")) else
            "dev.ucp.shopping.catalog.search" if request.url.path.endswith("/search") else None)
        if not root or root not in caps:
            return JSONResponse({"ucp": {"version": VERSION, "status": "error", "capabilities": {}},
              "messages": [{"type": "error", "code": "capabilities_incompatible",
                "content": "No mutually supported capability for this operation", "severity": "unrecoverable"}]}, status_code=200)
        if business_signing_key() is None:
            raise UCPError(503, "signature_missing", "Business response signing key not configured")
        body = await request.body()
        raw_headers = {k.lower(): v for k, v in request.headers.items()}
        identity = verify_request(request.method, request.headers.get("host", ""), request.url.path,
                                  request.url.query, raw_headers, body, profiles[url])
        # Nonces are transaction-bound and recorded atomically before execution.
        with conn() as db:
            db.execute("CREATE TABLE IF NOT EXISTS signature_nonces (profile TEXT NOT NULL, identity TEXT NOT NULL, "
                       "created_at INTEGER NOT NULL, PRIMARY KEY(profile, identity))")
            db.execute("DELETE FROM signature_nonces WHERE created_at<?", (int(time.time())-600,))
            try:
                db.execute("INSERT INTO signature_nonces VALUES (?,?,?)", (url, identity, int(time.time())))
            except Exception as exc:
                if not (exc.__class__.__name__ in ("UniqueViolation", "IntegrityError") or "unique" in str(exc).lower()):
                    raise
                raise UCPError(401, "signature_invalid", "Replay detected")
        token = ACTIVE_CAPS.set({root: caps[root]})
        try:
            response = await call_next(request)
            chunks = [chunk async for chunk in response.body_iterator]
            payload = b''.join(chunks)
            content_type = response.headers.get('content-type', 'application/json')
            sign_headers = response_signature(response.status_code, payload, content_type,
                                               business_signing_key(), int(time.time()))
            headers_out = {k:v for k,v in response.headers.items() if k.lower() not in ('content-length', 'transfer-encoding')}
            headers_out.update(sign_headers)
            return StarletteResponse(content=payload, status_code=response.status_code, headers=headers_out,
                                     background=response.background)
        finally:
            ACTIVE_CAPS.reset(token)
    except UCPError as exc:
        return JSONResponse({"code": exc.code, "content": exc.detail}, status_code=exc.status)




def init_db():
    with conn() as db:
        if is_postgres():
            init_postgres_schema(db)
        else:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
          id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          api_key_hash TEXT NOT NULL, checkout_url TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS platform_bindings (
          tenant_id TEXT NOT NULL, profile_url TEXT NOT NULL,
          PRIMARY KEY(tenant_id, profile_url),
          FOREIGN KEY(tenant_id) REFERENCES tenants(id));
        CREATE TABLE IF NOT EXISTS products (
          tenant_id TEXT NOT NULL, sku TEXT NOT NULL, title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL CHECK(price_cents>=0),
          stock INTEGER NOT NULL CHECK(stock>=0), PRIMARY KEY(tenant_id,sku),
          FOREIGN KEY(tenant_id) REFERENCES tenants(id));
        CREATE TABLE IF NOT EXISTS carts (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, status TEXT NOT NULL,
          body TEXT NOT NULL, created_at INTEGER NOT NULL,
          FOREIGN KEY(tenant_id) REFERENCES tenants(id));
        CREATE TABLE IF NOT EXISTS checkouts (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, status TEXT NOT NULL,
          body TEXT NOT NULL, created_at INTEGER NOT NULL,
          FOREIGN KEY(tenant_id) REFERENCES tenants(id));
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL,
          event_type TEXT NOT NULL, resource_id TEXT, created_at INTEGER NOT NULL,
          FOREIGN KEY(tenant_id) REFERENCES tenants(id));
        CREATE TABLE IF NOT EXISTS idempotency (
          tenant_id TEXT NOT NULL, key TEXT NOT NULL, fingerprint TEXT NOT NULL,
          response_json TEXT NOT NULL, PRIMARY KEY(tenant_id,key));
        """)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_api_key_hash ON tenants(api_key_hash)")
        if DEMO_MODE:
            db.execute("INSERT INTO tenants VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING", (
                "demo", "demo", "Loja Demo", hashlib.sha256(SEED_KEY.encode()).hexdigest(),
                "https://example.com/checkout"))
            db.execute("INSERT INTO platform_bindings VALUES (?,?) ON CONFLICT DO NOTHING", (
                "demo", "https://agent.example/profiles/demo.json"))
            samples = [
                ("demo", "CAMBIO-001", "Engrenagem cambio 4x4", "Peça de transmissão automotiva", 12990, 8),
                ("demo", "OLEO-001", "Oleo essencial lavanda", "Frasco 10 ml", 4590, 30),
                ("demo", "FILTRO-001", "Filtro de ar", "Filtro para veículos", 3490, 0),
            ]
            db.executemany("INSERT INTO products VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING", samples)


def parse_agent_profile(value: str | None) -> str | None:
    """Parse the UCP-Agent RFC 8941 dictionary member form we support.

    This is intentionally a narrow parser: unsupported structured-field syntax is
    rejected rather than guessing an agent identity. It is not an RFC 8941 parser.
    """
    if value is None:
        return None
    match = re.fullmatch(r'\s*profile="(https://[^"\s]+)"\s*', value)
    if not match:
        raise HTTPException(400, "Malformed UCP-Agent; expected profile=\"https://...\"")
    profile = match.group(1)
    parsed = urlsplit(profile)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname or len(profile) > 2048:
        raise HTTPException(400, "Invalid UCP-Agent profile URL")
    return profile


def require_tenant(x_api_key: Annotated[str | None, Header()] = None,
                   ucp_agent: Annotated[str | None, Header()] = None):
    if not x_api_key:
        raise HTTPException(401, "X-API-Key required")
    claimed_profile = parse_agent_profile(ucp_agent)
    if not DEMO_MODE and not claimed_profile:
        raise HTTPException(400, "UCP-Agent is required")
    digest = hashlib.sha256(x_api_key.encode()).hexdigest()
    with conn() as db:
        tenants = db.execute("SELECT * FROM tenants WHERE api_key_hash=?", (digest,)).fetchall()
        for tenant in tenants:
            if hmac.compare_digest(digest, tenant["api_key_hash"]):
                if claimed_profile:
                    binding = db.execute(
                        "SELECT 1 FROM platform_bindings WHERE tenant_id=? AND profile_url=?",
                        (tenant["id"], claimed_profile)).fetchone()
                    if not binding:
                        raise HTTPException(403, "Authenticated key is not bound to UCP-Agent")
                return dict(tenant)
    raise HTTPException(401, "Invalid API key")

def meter(db, tenant_id: str, event_type: str, resource_id: str | None = None):
    db.execute("INSERT INTO events(tenant_id,event_type,resource_id,created_at) VALUES (?,?,?,?)",
               (tenant_id, event_type, resource_id, int(time.time())))


def product_view(row, tenant):
    amount = row["price_cents"]
    return {
        "id": row["sku"], "handle": row["sku"].lower(), "title": row["title"],
        "description": {"plain": row["description"]},
        "url": f"{BASE_URL}/demo/products/{quote(row['sku'])}",
        "price_range": {"min": {"amount": amount, "currency": "BRL"},
                        "max": {"amount": amount, "currency": "BRL"}},
        "variants": [{"id": row["sku"], "sku": row["sku"], "price": {"amount": amount, "currency": "BRL"},
                      "availability": {"available": row["stock"] > 0}}],
    }


def meta(*capabilities):
    negotiated = ACTIVE_CAPS.get()
    caps = {f"dev.ucp.shopping.{c}": [{"version": VERSION}] for c in capabilities}
    if negotiated is not None:
        caps = {k:v for k,v in caps.items() if k in negotiated}
    return {"version": VERSION, "capabilities": caps}


@app.get("/healthz")
def health():
    return {"status": "ok", "version": "0.4.1", "demo": DEMO_MODE, "strict_ucp": STRICT_UCP}


@app.get("/readyz")
def readiness():
    """Real database ping; do not substitute for full UCP conformance."""
    try:
        with conn() as db:
            db.execute("SELECT 1").fetchone()
    except Exception:
        raise HTTPException(503, "Database is unavailable")
    return {"status": "ready", "database": "postgresql" if is_postgres() else "sqlite-demo"}


@app.get("/.well-known/ucp")
def ucp_profile(response: Response):
    """Advertise implemented transport capabilities, not unsupported payment/checkout."""
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["ETag"] = f'W/"ucp-{VERSION}-v04"'
    public_keys = [jwk_from_private(business_signing_key())] if business_signing_key() else []
    return {"keys": public_keys, "ucp": {
        "version": VERSION,
        "services": {"dev.ucp.shopping": [{"version": VERSION, "spec": f"{SPEC}/specification/overview/",
            "transport": "rest", "schema": f"{SPEC}/services/shopping/rest.openapi.json",
            "endpoint": f"{BASE_URL}/ucp/v1"}]},
        "capabilities": {
            f"dev.ucp.shopping.catalog.{name}": [{"version": VERSION,
                "spec": f"{SPEC}/specification/shopping/catalog/{name}",
                "schema": f"{SPEC}/schemas/shopping/catalog_{name}.json"}]
            for name in ("search", "lookup")} | {
            "dev.ucp.shopping.cart": [{"version": VERSION,
                "spec": f"{SPEC}/specification/shopping/cart",
                "schema": f"{SPEC}/schemas/shopping/cart.json"}]},
        "payment_handlers": {}
    }}


class Pagination(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=512)


class SearchIn(BaseModel):
    query: str = Field(default="", max_length=200)
    pagination: Pagination = Field(default_factory=Pagination)


class ProductDetailIn(BaseModel):
    id: str = Field(min_length=1, max_length=120)


class LookupIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


def cursor_encode(tenant_id: str, sku: str, query: str) -> str:
    payload = json.dumps([tenant_id, sku, query], separators=(",", ":")).encode()
    signature = hmac.new(SEED_KEY.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")


def cursor_decode(token: str, tenant_id: str, query: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload, signature = raw[:-32], raw[-32:]
        if not hmac.compare_digest(hmac.new(SEED_KEY.encode(), payload, hashlib.sha256).digest(), signature):
            raise ValueError("Invalid signature")
        tenant, sku, saved_query = json.loads(payload)
        if tenant != tenant_id or query != saved_query:
            raise ValueError("Cursor scope mismatch")
        return str(sku)
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(400, "Invalid catalog cursor") from exc


@app.post("/ucp/v1/catalog/search")
def catalog_search(payload: SearchIn, tenant=Depends(require_tenant)):
    after = cursor_decode(payload.pagination.cursor, tenant["id"], payload.query) if payload.pagination.cursor else ""
    escaped = payload.query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    pattern = "%" + escaped + "%"
    with conn() as db:
        rows = db.execute("SELECT * FROM products WHERE tenant_id=? AND sku>? AND "
            "(title LIKE ? ESCAPE '!' OR sku LIKE ? ESCAPE '!') ORDER BY sku LIMIT ?",
            (tenant["id"], after, pattern, pattern, payload.pagination.limit + 1)).fetchall()
        meter(db, tenant["id"], "catalog_search")
    has_next = len(rows) > payload.pagination.limit
    page = rows[:payload.pagination.limit]
    result = {"ucp": meta("catalog.search"), "products": [product_view(row, tenant) for row in page]}
    result["pagination"] = {"has_next_page": has_next}
    if has_next:
        result["pagination"]["cursor"] = cursor_encode(tenant["id"], page[-1]["sku"], payload.query)
    return result


@app.post("/ucp/v1/catalog/lookup")
def catalog_lookup(payload: LookupIn, tenant=Depends(require_tenant)):
    with conn() as db:
        placeholders = ",".join("?" for _ in payload.ids)
        rows = db.execute(f"SELECT * FROM products WHERE tenant_id=? AND sku IN ({placeholders})",
                          (tenant["id"], *payload.ids)).fetchall()
        meter(db, tenant["id"], "catalog_lookup")
    found = {row["sku"]: row for row in rows}
    result = {"ucp": meta("catalog.lookup"),
              "products": [product_view(found[sku], tenant) for sku in dict.fromkeys(payload.ids) if sku in found]}
    missing = [sku for sku in dict.fromkeys(payload.ids) if sku not in found]
    if missing:
        result["messages"] = [{"type": "info", "code": "not_found", "content": sku} for sku in missing]
    return result


@app.post("/ucp/v1/catalog/product")
def catalog_product(payload: ProductDetailIn, tenant=Depends(require_tenant)):
    with conn() as db:
        row = db.execute("SELECT * FROM products WHERE tenant_id=? AND sku=?",
                         (tenant["id"], payload.id)).fetchone()
        meter(db, tenant["id"], "catalog_product")
    if not row:
        return {"ucp": {"version": VERSION, "status": "error"},
                "messages": [{"type": "error", "code": "not_found", "content": "Product not found", "severity": "unrecoverable"}]}
    return {"ucp": meta("catalog.lookup"), "product": product_view(row, tenant)}

class ItemRef(BaseModel):
    id: str = Field(min_length=1, max_length=120)


class LineItem(BaseModel):
    item: ItemRef
    quantity: int = Field(ge=1, le=100)


class CartIn(BaseModel):
    line_items: list[LineItem] = Field(min_length=1, max_length=30)


class CheckoutIn(CartIn):
    """Subset of checkout fields; no payment credentials are accepted in this MVP."""
    buyer: dict | None = None



def cart_data(db, tenant, payload: CartIn, cart_id: str):
    grouped = {}
    for line in payload.line_items:
        grouped[line.item.id] = grouped.get(line.item.id, 0) + line.quantity
    if any(q > 100 for q in grouped.values()):
        raise HTTPException(422, "Maximum 100 units per SKU")
    lines = []
    grand_total = 0
    for sku, qty in grouped.items():
        row = db.execute("SELECT * FROM products WHERE tenant_id=? AND sku=?", (tenant["id"], sku)).fetchone()
        if not row:
            raise HTTPException(422, f"Unknown SKU: {sku}")
        if qty > row["stock"]:
            raise HTTPException(409, f"Insufficient stock: {sku}")
        subtotal = row["price_cents"] * qty
        grand_total += subtotal
        lines.append({"id": f"li_{len(lines)+1}", "item": {"id": sku, "title": row["title"],
                      "price": row["price_cents"]}, "quantity": qty,
                      "totals": [{"type": "subtotal", "amount": subtotal}, {"type": "total", "amount": subtotal}]})
    return {"ucp": meta("cart"), "id": cart_id, "currency": "BRL", "line_items": lines,
            "totals": [{"type": "subtotal", "amount": grand_total}, {"type": "total", "amount": grand_total}],
            "continue_url": f"{BASE_URL}/demo/handoff/{quote(cart_id)}"}


@app.post("/ucp/v1/carts", status_code=201)
def create_cart(payload: CartIn, tenant=Depends(require_tenant), idempotency_key: Annotated[str | None, Header()] = None):
    if idempotency_key is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", idempotency_key):
        raise HTTPException(422, "Invalid Idempotency-Key")
    fingerprint = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            if idempotency_key:
                # PostgreSQL serialization across Cloud Run instances: identical
                # tenant/key pair must not create two carts concurrently.
                if is_postgres():
                    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
                               (tenant["id"] + ":" + idempotency_key,))
                old = db.execute("SELECT * FROM idempotency WHERE tenant_id=? AND key=?",
                                 (tenant["id"], idempotency_key)).fetchone()
                if old:
                    if old["fingerprint"] != fingerprint:
                        raise HTTPException(409, "Idempotency key reused for different request")
                    db.execute("COMMIT")
                    return json.loads(old["response_json"])
            cart_id = "cart_" + secrets.token_urlsafe(16)
            response = cart_data(db, tenant, payload, cart_id)
            db.execute("INSERT INTO carts VALUES (?,?,?,?,?)",
                       (cart_id, tenant["id"], "active", json.dumps(response), int(time.time())))
            if idempotency_key:
                db.execute("INSERT INTO idempotency VALUES (?,?,?,?)",
                           (tenant["id"], idempotency_key, fingerprint, json.dumps(response)))
            meter(db, tenant["id"], "cart_created", cart_id)
            db.execute("COMMIT")
            return response
        except Exception:
            db.execute("ROLLBACK")
            raise


@app.put("/ucp/v1/carts/{cart_id}")
def update_cart(cart_id: str, payload: CartIn, tenant=Depends(require_tenant)):
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            old = db.execute("SELECT * FROM carts WHERE id=? AND tenant_id=?", (cart_id, tenant["id"])).fetchone()
            if not old:
                raise HTTPException(404, "Cart not found")
            if old["status"] != "active":
                raise HTTPException(409, "Cart is not active")
            response = cart_data(db, tenant, payload, cart_id)
            db.execute("UPDATE carts SET body=? WHERE id=? AND tenant_id=?", (json.dumps(response), cart_id, tenant["id"]))
            meter(db, tenant["id"], "cart_updated", cart_id)
            db.execute("COMMIT")
            return response
        except Exception:
            db.execute("ROLLBACK")
            raise


@app.get("/ucp/v1/carts/{cart_id}")
def get_cart(cart_id: str, tenant=Depends(require_tenant)):
    with conn() as db:
        row = db.execute("SELECT * FROM carts WHERE tenant_id=? AND id=?", (tenant["id"], cart_id)).fetchone()
    if not row:
        raise HTTPException(404, "Cart not found")
    data = json.loads(row["body"])
    if row["status"] != "active":
        data["blitz_status"] = "cancelled"
    return data


@app.post("/ucp/v1/carts/{cart_id}/cancel")
def cancel_cart(cart_id: str, tenant=Depends(require_tenant)):
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM carts WHERE tenant_id=? AND id=?", (tenant["id"], cart_id)).fetchone()
        if not row:
            db.execute("ROLLBACK")
            raise HTTPException(404, "Cart not found")
        if row["status"] == "active":
            db.execute("UPDATE carts SET status='cancelled' WHERE id=? AND tenant_id=?", (cart_id, tenant["id"]))
            meter(db, tenant["id"], "cart_cancelled", cart_id)
        db.execute("COMMIT")
    data = json.loads(row["body"])
    data["messages"] = [{"type": "info", "code": "cancelled", "content": "Cart cancelled"}]
    return data


def checkout_data(db, tenant, payload: CheckoutIn, checkout_id: str):
    cart = cart_data(db, tenant, payload, checkout_id)
    cart["ucp"] = meta("checkout")
    cart["status"] = "requires_escalation"
    cart["messages"] = [{
        "type": "info", "code": "merchant_handoff_required",
        "content": "Complete the purchase in the merchant checkout; no payment is processed by Blitz.",
        "severity": "requires_buyer_review"
    }]
    # Do not return or store buyer data: identity/PII handling is out of scope.
    cart["continue_url"] = f"{BASE_URL}/demo/checkout-handoff/{quote(checkout_id)}"
    return cart


@app.post("/ucp/v1/checkout-sessions", status_code=201, include_in_schema=False)
def create_checkout(payload: CheckoutIn, tenant=Depends(require_tenant)):
    """EXPERIMENTAL — not advertised in discovery; does not create payable orders."""
    if not DEMO_MODE:
        raise HTTPException(501, "Experimental checkout is disabled outside demo mode")
    if payload.buyer is not None:
        raise HTTPException(422, "Buyer information is not accepted in the experimental checkout")
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            checkout_id = "chk_" + secrets.token_urlsafe(16)
            result = checkout_data(db, tenant, payload, checkout_id)
            db.execute("INSERT INTO checkouts VALUES (?,?,?,?,?)", (
                checkout_id, tenant["id"], "requires_escalation", json.dumps(result), int(time.time())))
            meter(db, tenant["id"], "checkout_draft_created", checkout_id)
            db.execute("COMMIT")
            return result
        except Exception:
            db.execute("ROLLBACK")
            raise


@app.get("/ucp/v1/checkout-sessions/{checkout_id}", include_in_schema=False)
def get_checkout(checkout_id: str, tenant=Depends(require_tenant)):
    if not DEMO_MODE:
        raise HTTPException(501, "Experimental checkout disabled outside demo mode")
    with conn() as db:
        row = db.execute("SELECT * FROM checkouts WHERE tenant_id=? AND id=?", (
            tenant["id"], checkout_id)).fetchone()
    if not row:
        raise HTTPException(404, "Checkout not found")
    return json.loads(row["body"])


@app.put("/ucp/v1/checkout-sessions/{checkout_id}", include_in_schema=False)
def update_checkout(checkout_id: str, payload: CheckoutIn, tenant=Depends(require_tenant)):
    if not DEMO_MODE:
        raise HTTPException(501, "Experimental checkout disabled outside demo mode")
    if payload.buyer is not None:
        raise HTTPException(422, "Buyer information is not accepted in the experimental checkout")
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM checkouts WHERE tenant_id=? AND id=?", (
                tenant["id"], checkout_id)).fetchone()
            if not row:
                raise HTTPException(404, "Checkout not found")
            if row["status"] != "requires_escalation":
                raise HTTPException(409, "Checkout is no longer editable")
            result = checkout_data(db, tenant, payload, checkout_id)
            db.execute("UPDATE checkouts SET body=? WHERE id=? AND tenant_id=?", (
                json.dumps(result), checkout_id, tenant["id"]))
            meter(db, tenant["id"], "checkout_draft_updated", checkout_id)
            db.execute("COMMIT")
            return result
        except Exception:
            db.execute("ROLLBACK")
            raise


@app.post("/ucp/v1/checkout-sessions/{checkout_id}/cancel", include_in_schema=False)
def cancel_checkout(checkout_id: str, tenant=Depends(require_tenant)):
    if not DEMO_MODE:
        raise HTTPException(501, "Experimental checkout disabled outside demo mode")
    with conn() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM checkouts WHERE tenant_id=? AND id=?", (
                tenant["id"], checkout_id)).fetchone()
            if not row:
                raise HTTPException(404, "Checkout not found")
            if row["status"] != "cancelled":
                db.execute("UPDATE checkouts SET status='cancelled' WHERE id=? AND tenant_id=?", (
                    checkout_id, tenant["id"]))
                meter(db, tenant["id"], "checkout_draft_cancelled", checkout_id)
            result = json.loads(row["body"])
            result["status"] = "cancelled"
            db.execute("UPDATE checkouts SET body=? WHERE id=? AND tenant_id=?", (
                json.dumps(result), checkout_id, tenant["id"]))
            db.execute("COMMIT")
            return result
        except Exception:
            db.execute("ROLLBACK")
            raise


@app.post("/ucp/v1/checkout-sessions/{checkout_id}/complete", include_in_schema=False)
def complete_checkout(checkout_id: str, tenant=Depends(require_tenant)):
    if not DEMO_MODE:
        raise HTTPException(501, "Experimental checkout disabled outside demo mode")
    with conn() as db:
        row = db.execute("SELECT 1 FROM checkouts WHERE tenant_id=? AND id=?", (
            tenant["id"], checkout_id)).fetchone()
    if not row:
        raise HTTPException(404, "Checkout not found")
    raise HTTPException(501, "No PSP / order fulfillment adapter connected; payment completion disabled")


@app.get("/demo/checkout-handoff/{checkout_id}", response_class=HTMLResponse)
def checkout_handoff(checkout_id: str):
    if not DEMO_MODE:
        raise HTTPException(404, "Handoff requires a merchant integration")
    with conn() as db:
        row = db.execute("SELECT status FROM checkouts WHERE id=?", (checkout_id,)).fetchone()
    if not row or row["status"] != "requires_escalation":
        raise HTTPException(404, "Checkout unavailable")
    return "<html><body><h1>Blitz Demo</h1><p>No payment or order is created.</p></body></html>"


@app.get("/api/usage")
def usage(tenant=Depends(require_tenant)):
    with conn() as db:
        rows = db.execute("SELECT event_type, COUNT(*) AS count FROM events WHERE tenant_id=? GROUP BY event_type ORDER BY event_type", (tenant["id"],)).fetchall()
    return {"tenant": tenant["slug"], "events": {r["event_type"]: r["count"] for r in rows},
            "note": "Telemetry only. No real billing, deduplication across all endpoints, or quotas yet."}


@app.get("/demo/handoff/{cart_id}", response_class=HTMLResponse)
def handoff(cart_id: str):
    if not DEMO_MODE:
        raise HTTPException(404, "Demo handoff disabled")
    # No payment, purchase confirmation, or externally hosted arbitrary redirect here.
    with conn() as db:
        row = db.execute("SELECT id,status FROM carts WHERE id=?", (cart_id,)).fetchone()
    if not row or row["status"] != "active":
        raise HTTPException(404, "Cart unavailable")
    return "<html><body><h1>Blitz Commerce OS — Demonstration only</h1><p>No payment is taken. Merchant checkout integration is not yet connected.</p></body></html>"


@app.get("/demo/products/{sku}")
def demo_product(sku: str):
    # Deliberately a demonstration, not an actual merchant storefront.
    with conn() as db:
        row = db.execute("SELECT * FROM products WHERE tenant_id='demo' AND sku=?", (sku,)).fetchone()
    if not DEMO_MODE or not row:
        raise HTTPException(404, "Not found")
    return {"sku": row["sku"], "title": row["title"], "price_cents": row["price_cents"],
            "warning": "Demo catalog. Not a merchant product page."}


@app.get("/")
def root():
    return {"product": "Blitz Commerce OS", "docs": "/docs", "ucp_discovery": "/.well-known/ucp", "warning": "MVP demo, not production"}
