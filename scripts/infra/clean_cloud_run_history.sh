#!/bin/bash

# Define your objects
project="i4g-dev"
region="us-central1"
jobs="analytics-refresh classification-sweeper dossier-queue generate-reports ingest-bootstrap ingest-network-smoke process-intakes retention-purge ssi-ecx-poller"
services="core-svc i4g-console ssi-svc"

for job in $jobs; do
    gcloud run jobs executions list \
        --job=$job \
        --region=$region \
        --project=$project \
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
        --project=$project \
        --quiet
done

for service in $services; do
    gcloud run revisions list \
      --service=$service \
      --region=$region \
      --project=$project \
      --format=json 2>/dev/null | \
    python3 -c "
import json, sys
data = json.load(sys.stdin)
for rev in data:
    conditions = (rev.get('status') or {}).get('conditions', [])
    active_cond = next((c for c in conditions if c.get('type') == 'Active'), None)
    if active_cond and active_cond.get('status') == 'False':
        name = (rev.get('metadata') or {}).get('name') or rev.get('name', '').rsplit('/', 1)[-1]
        if name:
            print(name)
" | xargs -r -L1 gcloud run revisions delete \
      --region=$region \
      --project=$project \
      --quiet
done
