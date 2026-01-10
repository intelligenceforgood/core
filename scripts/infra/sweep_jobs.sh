#!/bin/bash

# Define your objects
jobs="account-list classification-sweeper dossier-queue  generate-reports ingest-bootstrap ingest-network-smoke process-intakes"

for job in $jobs; do
    gcloud run jobs executions list \
    --job=$job \
    --region=us-central1 \
    --format="value(metadata.name)" | \
    xargs -I {} gcloud run jobs executions delete {} \
    --region=us-central1 \
    --quiet
done