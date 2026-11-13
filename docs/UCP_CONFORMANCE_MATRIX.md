# v0.4.1 official verification gate

Official GitHub v2026-08-25 spec is pinned (SHA cd78fb38e819de77d9b527d110476eccb876f1bd). Official CLI pipeline created but **not yet run**. Four selected shapes are targeted; no claims of passing. See `docs/OFFICIAL_UCP_GITHUB_QA.md`.

# UCP 2026-08-25 — Conformance evidence ledger (v0.4.0)

**NON-CONFORMANT / NOT CERTIFIED.** This is a list of evidence, not a claim of certification.

| Area | Evidence | Gap |
|---|---|---|
| Discovery | `GET /.well-known/ucp`, local pytest | Merchant-specific profile, schema verification and externally reachable HTTPS not tested |
| Catalog search/lookup | Pydantic handlers, local HTTP tests | Official JSON Schema conformance not checked; unknown fields/context |
| Cart | Local create/read/update/cancel and idempotency tests | Official schema validation, full state semantics and concurrency soak test |
| HTTP Signatures | Local Ed25519 tests | Incomplete RFC 8941/9421, WBA/multisignature |
| Capability negotiation | Exact subset tests | Extension dependencies and multi-version selection incomplete |
| Authority Binding | Only official namespace literals currently declared | External schema resolver and vendor schemas unimplemented |
| Checkout | Disabled for real payments | PSP, fulfillment, receipt, webhooks, identity/mandates |
| PostgreSQL | SQL migration + adapter + CI job included | Real PG test still awaiting CI execution; no RLS |
| Interoperability | No results | No external conformance suite/third-party agent run |

Official sources:
- https://ucp.dev/2026-08-25/specification/overview/
- https://ucp.dev/2026-08-25/services/shopping/rest.openapi.json
- https://ucp.dev/2026-08-25/schemas/shopping/cart.json

## Next verification gates

1. Run the GitHub PostgreSQL CI job and resolve any failures.
2. Download and review exact official contract files using manual workflow.
3. Run offline schema diagnostic; correct payloads and errors until the selected
   operations pass with no missing/incorrect extension fields.
4. Expand to the full official API and all active, negotiated capabilities.
5. Run security/interoperability testing with external UCP clients.
