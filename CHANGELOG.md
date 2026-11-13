# v0.4.1
- Add pinned official GitHub UCP tag/commit snapshot and hash manifest.
- Add fail-closed `ucp-schema` official API response contract validation in GitHub Actions.
- Add 6 unit tests for provenance and pipeline safeguards.
- Keep UCP compatibility status UNVERIFIED pending CI.

# Changelog

## v0.4.0 — 2026-11-13

- Added PostgreSQL/Cloud SQL driver adapter and idempotent PostgreSQL bootstrap schema.
- Added tenant-indexed API key lookup and per-tenant/key PostgreSQL advisory lock on cart creation.
- Added PostgreSQL 16 Docker Compose setup, Dockerfile support and readiness check.
- Added private Cloud Run deployment script and GCP operator runbook (not deployed).
- Added GitHub Actions regression CI, PostgreSQL service integration job and
  manual, reviewable upstream UCP document synchronization.
- Added version-pinned UCP schema lock/verification and partial offline JSON Schema diagnostics.
- Preserved v0.3.0 API and security tests; no payment integration.
- Local QA: 34 passed, 2 skipped; HTTP smoke PASS. Real PostgreSQL and schema
  downloads require external runner/network and remain unverified here.

## v0.3.0 — 2026-11-13

- Ed25519 signatures RFC 9421 subset, pinned profiles, replay defense,
  capability intersection and experimental catalog/cart profile.
