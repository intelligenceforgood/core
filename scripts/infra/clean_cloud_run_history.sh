#!/bin/bash

# Define your objects
region="us-central1"
jobs="account-list classification-sweeper dossier-queue  generate-reports ingest-bootstrap ingest-network-smoke process-intakes"
services="fastapi-gateway i4g-console"

for job in $jobs; do
    gcloud run jobs executions list \
    --job=$job \
    --region=$region \
    --format="value(metadata.name)" | \
    xargs -I {} gcloud run jobs executions delete {} \
    --region=$region \
    --quiet
done

for service in $services; do
    gcloud run revisions list \
      --service=$service \
      --region=us-central1 \
      --filter="status.conditions.type:Active AND status.conditions.status:'False'" \
      --format='value(metadata.name)' \
    | xargs -r -L1 gcloud run revisions delete \
      --region=us-central1 \
      --quiet
done