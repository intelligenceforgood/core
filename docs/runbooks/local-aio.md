# I4G Local — Quick-Start Runbook

A single Docker image with everything pre-loaded: Core API, SSI API, UI Console, Ollama LLM, Playwright browser, and sample data. No external services, accounts, or API keys needed.

## Prerequisites

- **Docker Desktop** — [docker.com/get-started](https://www.docker.com/get-started/) (macOS, Windows, or Linux)
- Allocate **≥ 8 GB RAM** in Docker Desktop → Settings → Resources (Ollama needs memory for the LLM)

## 1. Download the Image

1. Download `i4g-local.tar.gz` from the shared [Google Drive folder](https://drive.google.com/drive/folders/0AMtQF72E2PBAUk9PVA) (~8–10 GB compressed).
2. Load it into Docker:

```bash
docker load < i4g-local.tar.gz
```

## 2. Run

```bash
docker run -d --name i4g \
  -p 3000:3000 \
  -p 8000:8000 \
  -p 8100:8100 \
  i4g-local
```

Wait ~10 seconds for all services to start, then open **http://localhost:3000** in your browser.

## 3. What's Running

| Service    | URL                        | Purpose                 |
| ---------- | -------------------------- | ----------------------- |
| UI Console | http://localhost:3000      | Analyst web interface   |
| Core API   | http://localhost:8000/docs | Core API (Swagger docs) |
| SSI API    | http://localhost:8100/docs | SSI API (Swagger docs)  |

Authentication is disabled (mock identity) — you're automatically signed in as a test user.

## 4. Verify It's Working

```bash
# Check all services are running:
docker logs i4g 2>&1 | grep "RUNNING"

# Expected output (4 lines):
#   success: ollama entered RUNNING state
#   success: core-api entered RUNNING state
#   success: ssi-api entered RUNNING state
#   success: ui-console entered RUNNING state
```

## 5. Stop / Restart

```bash
docker stop i4g          # stop
docker start i4g         # restart (data persists)
docker rm -f i4g         # remove completely
```

## Troubleshooting

| Symptom                     | Fix                                                                                   |
| --------------------------- | ------------------------------------------------------------------------------------- |
| Port already in use         | Change host ports: `-p 3001:3000 -p 8001:8000 -p 8101:8100` and open `localhost:3001` |
| UI loads but API calls fail | Wait 15 seconds — Core API starts last. Check `docker logs i4g`                       |
| Ollama responses are slow   | Expected on CPU. Allocate more RAM in Docker Desktop settings                         |
| Container exits immediately | Run `docker logs i4g` to see the error. Usually a port conflict                       |

## Notes

- **LLM**: Runs Ollama with `tinyllama` (1.1B params, CPU-only). Responses work but are not production quality — this is for testing workflows, not evaluating output.
- **Data**: Pre-loaded with sample SQLite + Chroma data. Resets to the snapshot each time you `docker rm` and re-run.
- **Image size**: ~15 GB. First pull takes a while, but subsequent starts are instant.
