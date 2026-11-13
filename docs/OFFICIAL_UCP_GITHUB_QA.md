# Official UCP GitHub conformance gate — v0.4.1

## Verified upstream identities

- Specification: https://github.com/Universal-Commerce-Protocol/ucp
- **Release tag:** `v2026-08-25`
- **Full commit SHA:** `cd78fb38e819de77d9b527d110476eccb876f1bd`
- Official CLI source: https://github.com/Universal-Commerce-Protocol/ucp-schema
- CLI: `ucp-schema validate`, documented upstream; see README in that repository.

The full SHA was verified from the official GitHub tagged commit page. The binary
`ucp-schema` is installed via crates.io using Cargo.lock (`--locked`) but its
package version is **not yet pinned**; pin after first successful CI run and review.

## What the CI actually does

Workflow: `.github/workflows/ucp-official.yml`, job `official-ucp`.

1. Fetch the specification from the official GitHub repository.
2. Check out the **exact commit**, require tag `v2026-08-25` on that commit.
3. Copy `source/` into ephemeral `contracts/2026-08-25/github/source` and compute a per-file SHA-256 manifest.
4. Re-read the snapshot and verify hashes and inventory (fail on tampering).
5. Install official `ucp-schema` CLI using Cargo.
6. Boot FastAPI TestClient in DEMO mode with ephemeral SQLite and request the following **real** endpoints:
   - `POST /ucp/v1/catalog/search` → `catalog_search.json` `search` response
   - `POST /ucp/v1/catalog/lookup` → `catalog_lookup.json` `lookup` response
   - `POST /ucp/v1/catalog/product` → `catalog_lookup.json` `get_product` response
   - `POST /ucp/v1/carts` → `cart.json` `create` response
7. Save each payload to JSON, validate using the **official** CLI with `--schema` and `--op`, fail on validation errors or missing source/CLI.
8. Upload `official-qa.json`, actual JSON responses, and source hash manifest as CI artifacts even on failures.

## GitHub setup (by repository administrator)

1. Create a **private** repository `blitz-commerce-os`, push this directory, and open Actions.
2. In **Actions**, run `Official UCP v2026-08-25 contract gate`, or push a commit and let it run.
3. Read the resulting `official-qa.json` artifact to identify exact contract differences. Fix handlers/mappers, re-run until green.
4. In **Settings → Rules → Rulesets** (or branch protection), require `official-ucp`, `test`, and `postgres-integration` before merge to `main`.
5. Do not enable auto deploy to production merely because these jobs pass. HTTP signature, payments and interoperability gates remain open.

## Reproducing with a computer that can access GitHub

```bash
git clone https://github.com/Universal-Commerce-Protocol/ucp.git /tmp/official-ucp
git -C /tmp/official-ucp checkout --detach cd78fb38e819de77d9b527d110476eccb876f1bd
git -C /tmp/official-ucp tag --points-at HEAD | grep -Fx v2026-08-25
python scripts/github_ucp_contracts.py --checkout /tmp/official-ucp
python scripts/github_ucp_contracts.py --verify
cargo install ucp-schema --locked
python -m scripts.ucp_official_qa --report-dir reports/ucp
cat reports/ucp/official-qa.json
```

**Interpretation:** exit `0` means four selected API response shapes passed the
validator; exit `1` means incompatibility found; exit `2` means execution
prerequisites missing. This is not general UCP certification. A green unit test
suite must **never** be equated with a green official UCP job.

## Gaps / engineering TODOs

- Run the GitHub Actions official gate. It has **not** run in the current isolated environment.
- Resolve mismatches and expand contract cases to all required request and response operations (cart update/read/cancel, errors, checkout only once payments work).
- Validate complete capability negotiation and agent profile selection with the official validator.
- Pin and review Rust CLI release, third-party Actions SHAs and supply-chain dependencies.
- Run external-agent interoperability + transport/RFC 9421 security conformance suites.
- Docker/PostgreSQL CI must run before Cloud Run deployment.

**No UCP certification, production readiness or validated passing of official
contracts is claimed by this document.**
