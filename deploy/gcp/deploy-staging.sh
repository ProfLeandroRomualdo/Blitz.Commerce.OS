#!/usr/bin/env bash
# Explicitly private staging. Requires prepared project, Artifact Registry,
# Cloud SQL instance, database user, Secret Manager secrets, and service account.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${GCP_PROJECT:?GCP_PROJECT required}"
: "${GCP_REGION:?GCP_REGION required}"
: "${ARTIFACT_REPO:?ARTIFACT_REPO required}"
: "${CLOUD_RUN_SERVICE:?CLOUD_RUN_SERVICE required}"
: "${CLOUD_SQL_INSTANCE:?CLOUD_SQL_INSTANCE required}"
: "${DATABASE_URL_SECRET:?DATABASE_URL_SECRET required}"
: "${API_KEY_SECRET:?API_KEY_SECRET required}"
: "${PUBLIC_BASE_URL:?PUBLIC_BASE_URL required}"
: "${RUNTIME_SERVICE_ACCOUNT:?RUNTIME_SERVICE_ACCOUNT required}"
command -v gcloud >/dev/null
IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/${ARTIFACT_REPO}/${CLOUD_RUN_SERVICE}:v0.4.0"
echo "Building $IMAGE in project $GCP_PROJECT"
gcloud builds submit --project "$GCP_PROJECT" --tag "$IMAGE" .
gcloud run deploy "$CLOUD_RUN_SERVICE" \
  --project "$GCP_PROJECT" --region "$GCP_REGION" --image "$IMAGE" \
  --service-account "$RUNTIME_SERVICE_ACCOUNT" \
  --add-cloudsql-instances "${GCP_PROJECT}:${GCP_REGION}:${CLOUD_SQL_INSTANCE}" \
  --set-secrets "DATABASE_URL=${DATABASE_URL_SECRET}:latest,DEMO_API_KEY=${API_KEY_SECRET}:latest" \
  --set-env-vars "DEMO_MODE=true,STRICT_UCP=false,PUBLIC_BASE_URL=${PUBLIC_BASE_URL}" \
  --no-allow-unauthenticated --min-instances=0 --max-instances=2 \
  --concurrency=16 --cpu=1 --memory=512Mi --timeout=30s
printf '\nDeployment remains PRIVATE. Do not give allUsers invoker role.\n'
