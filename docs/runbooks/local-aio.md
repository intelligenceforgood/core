# I4G Local — Quick-Start Runbook

A single Docker image with everything pre-loaded: Core API, SSI API, UI Console, Ollama LLM, Playwright browser, and sample data. No external services, accounts, or API keys needed.

There are two image variants:

| Variant      | File                   | Target Hardware               | Baked-in Model     | Image Size |
| ------------ | ---------------------- | ----------------------------- | ------------------ | ---------- |
| **Standard** | `i4g-local.tar.gz`     | Mac (Apple Silicon) / any CPU | `tinyllama` (1.1B) | ~15 GB     |
| **GPU**      | `i4g-local-gpu.tar.gz` | Linux x86_64 + NVIDIA GPU     | `tinyllama` (1.1B) | ~15 GB     |

Both variants ship with a small model for fast transfer. The GPU variant includes CUDA support and can be upgraded to `llama3.1:8b` or larger after loading (see section 5).

## Prerequisites

**Both variants:**

- **Docker** — [docker.com/get-started](https://www.docker.com/get-started/) (Docker Desktop on Mac/Windows, Docker Engine on Linux)
- Allocate **≥ 8 GB RAM** in Docker Desktop → Settings → Resources (Ollama needs memory for the LLM)

**GPU variant only:**

- **Linux x86_64** with an NVIDIA GPU (tested on RTX 4090, 24 GB VRAM)
- **NVIDIA drivers** — `nvidia-smi` must work on the host
- **NVIDIA Container Toolkit** — [install guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

## 1. Download the Image

1. Download your variant from the shared [Google Drive folder](https://drive.google.com/drive/folders/0AMtQF72E2PBAUk9PVA):
   - Standard (Mac/CPU): `i4g-local.tar.gz` (~8–10 GB compressed)
   - GPU (Linux/NVIDIA): `i4g-local-gpu.tar.gz` (~15–20 GB compressed)
2. Load it into Docker:

```bash
# Standard
docker load < i4g-local.tar.gz

# GPU
docker load < i4g-local-gpu.tar.gz
```

## 2. Run

**Standard (Mac / CPU):**

```bash
docker run -d --name i4g \
  -p 3000:3000 \
  -p 8000:8000 \
  -p 8100:8100 \
  i4g-local
```

**GPU (Linux + NVIDIA):**

```bash
docker run -d --name i4g --gpus all \
  -p 3000:3000 \
  -p 8000:8000 \
  -p 8100:8100 \
  i4g-local-gpu
```

Wait ~10 seconds for all services to start, then open **http://localhost:3000** in your browser.

The GPU variant prints GPU info at startup — check with `docker logs i4g 2>&1 | head -20`.

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

**GPU variant — verify GPU acceleration:**

```bash
docker exec i4g nvidia-smi
# Should show your GPU (e.g., RTX 4090) and CUDA version.

docker exec i4g ollama ps
# Should show the current model loaded with GPU layers.
```

## 5. Upgrade Models (GPU Variant)

The GPU image ships with `tinyllama` to keep the download small. Once the image is loaded on the target machine, upgrade to better models — this downloads directly to the machine's SSD, no re-upload needed.

### Recommended: llama3.1:8b

Best balance of quality and speed on an RTX 4090. Fits entirely in 24 GB VRAM.

```bash
# Pull the models (one-time, ~5 GB total)
docker exec i4g ollama pull llama3.1:8b
docker exec i4g ollama pull nomic-embed-text

# Recreate with the upgraded models
docker rm -f i4g

docker run -d --name i4g --gpus all \
  -p 3000:3000 \
  -p 8000:8000 \
  -p 8100:8100 \
  -e I4G_LLM__CHAT_MODEL=llama3.1:8b \
  -e SSI_LLM__MODEL=llama3.1:8b \
  -e I4G_VECTOR__EMBED_MODEL=nomic-embed-text \
  i4g-local-gpu
```

### Even larger models

With 24 GB VRAM + 64 GB system RAM you have room for bigger models:

```bash
# 14B — excellent quality, fits in VRAM (~9 GB)
docker exec i4g ollama pull qwen2.5:14b

# 27B — near-frontier quality, fits in VRAM (~17 GB)
docker exec i4g ollama pull gemma2:27b

# 47B mixture-of-experts — partial GPU offload, uses system RAM too (~26 GB)
docker exec i4g ollama pull mixtral:8x7b
```

Then recreate the container with `-e I4G_LLM__CHAT_MODEL=<model> -e SSI_LLM__MODEL=<model>` as shown above.

> **Tip:** Use a Docker volume to persist pulled models across container recreations:
>
> ```bash
> docker volume create ollama-models
>
> docker run -d --name i4g --gpus all \
>   -v ollama-models:/root/.ollama \
>   -p 3000:3000 -p 8000:8000 -p 8100:8100 \
>   -e I4G_LLM__CHAT_MODEL=llama3.1:8b \
>   -e SSI_LLM__MODEL=llama3.1:8b \
>   -e I4G_VECTOR__EMBED_MODEL=nomic-embed-text \
>   i4g-local-gpu
> ```

## 6. Stop / Restart

```bash
docker stop i4g          # stop
docker start i4g         # restart (data persists)
docker rm -f i4g         # remove completely
```

## Troubleshooting

| Symptom                          | Fix                                                                                                                                                    |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Port already in use              | Change host ports: `-p 3001:3000 -p 8001:8000 -p 8101:8100` and open `localhost:3001`                                                                  |
| UI loads but API calls fail      | Wait 15 seconds — Core API starts last. Check `docker logs i4g`                                                                                        |
| Ollama responses are slow        | Expected on CPU. Allocate more RAM in Docker Desktop settings                                                                                          |
| Container exits immediately      | Run `docker logs i4g` to see the error. Usually a port conflict                                                                                        |
| GPU not detected (GPU variant)   | Ensure `--gpus all` is passed and `nvidia-smi` works on the host                                                                                       |
| "could not select device driver" | Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) and restart Docker |

## Notes

- **Standard LLM**: Runs Ollama with `tinyllama` (1.1B params, CPU-only). Responses work but are not production quality — this is for testing workflows, not evaluating output.
- **GPU LLM**: Ships with `tinyllama` for a small image. Upgrade to `llama3.1:8b` or larger after loading (see section 5). GPU acceleration is automatic when `--gpus all` is passed.
- **Data**: Pre-loaded with sample SQLite + Chroma data. Resets to the snapshot each time you `docker rm` and re-run.
- **Image sizes**: Both variants are ~15 GB uncompressed. The GPU variant is similar in size because large models are pulled after loading, not baked in.
