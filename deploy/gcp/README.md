# Blitz Commerce v0.4.0 — GCP staging (private)

This is an **operator runbook**, not evidence of deployment. No Google Cloud
resources were provisioned in the delivery environment.

## Decisions

- Region: `southamerica-east1` (São Paulo) unless quotas/costs require otherwise.
- Compute: Cloud Run; image: Artifact Registry; build: Cloud Build.
- Database: Cloud SQL PostgreSQL 16, private IAM-protected staging service.
- Secrets: Secret Manager; runtime identity: dedicated least-privilege SA.
- Future DNS: `api.blitz.ai` after verifying domain ownership. Never assume
  the domain is already owned or DNS records are provisioned.

## Prepare infrastructure (once)

1. Create/select a GCP project and billing account. Select a region.
2. Enable APIs: `run.googleapis.com`, `cloudbuild.googleapis.com`,
   `artifactregistry.googleapis.com`, `sqladmin.googleapis.com`,
   `secretmanager.googleapis.com`, `iam.googleapis.com`.
3. Create a Docker Artifact Registry repository; grant the Cloud Build identity
   permission to write images and the Cloud Run runtime identity read access.
4. Create a Cloud SQL PostgreSQL 16 instance, database `blitz`, and a dedicated
   application user, with backups, maintenance, and least privilege configured.
5. Create the runtime service account; grant `roles/cloudsql.client` for the
   instance and Secret Manager Secret Accessor **only on the two required secrets**.
6. Create `blitz-commerce-db-url` with a correctly URL-encoded password and
   Unix-socket DSN, for example:
   `postgresql://blitzapp:ENCODED_PASSWORD@/blitz?host=/cloudsql/PROJECT:REGION:INSTANCE`
   Add another secret holding a randomly generated demo API key (32+ random bytes).
7. Fill a local shell environment from `env.deploy.example` and add
   `RUNTIME_SERVICE_ACCOUNT=blitz-commerce-run@PROJECT.iam.gserviceaccount.com`.
8. Export variables and run `./deploy/gcp/deploy-staging.sh`.
9. Get a Cloud Run identity token from an authorized Google principal to test
   the endpoint. Without Cloud Run Invoker permissions, requests must be denied.
10. Map `api.blitz.ai` only after external HTTPS/DNS verification and risk review;
    Cloud Run domain mappings may have regional constraints. Prefer HTTPS Load
    Balancer with serverless NEG if required.

## Important

The staging deploy is IAM **private** and DEMO_MODE=true. It creates demo
products and credentials; never expose it as an Internet-facing merchant API.
`PUBLIC_BASE_URL` must be set to the final serving origin for correct URLs.
The application does not currently bootstrap a production tenant; DEMO_MODE=false
must not be enabled for external clients until provisioning and security reviews.

Cloud SQL connection counts scale with instance count and app concurrency;
load test before increasing Cloud Run max-instances. Cloud SQL and Artifact
Registry incur charges. Review IAM, budgets and logs before deployment.
