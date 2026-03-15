#!/bin/bash

# Define your objects
region="us-central1"
jobs="analytics-refresh classification-sweeper dossier-queue generate-reports ingest-bootstrap ingest-network-smoke process-intakes retention-purge ssi-ecx-poller"
services="core-svc i4g-console ssi-svc"

for job in $jobs; do
    gcloud run jobs executions list \
        --job=$job \
        --region=$region \
        --format=json 2>/dev/null | \
    python3 -c "
import json, sys
data = json.load(sys.stdin) if sys.stdin.readable() else []
for ex in data:
    ct = ex.get('completionTime') or (ex.get('status') or {}).get('completionTime')
    name = (ex.get('metadata') or {}).get('name') or ex.get('name', '').rsplit('/', 1)[-1]
    if ct and name:
        print(name)
" | xargs -r -I {} gcloud run jobs executions delete {} \
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
