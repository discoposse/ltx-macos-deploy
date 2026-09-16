# LTX-2 Deep Observability Stack

Portable, containerized observability for every LTX-2 inference run.

**What it tracks:**
- Input tokens, prompt length, ISL (Input Sequence Length)
- KV cache behavior & offloads (CPU/disk)
- Memory (unified, RSS, GPU approximation)
- CPU / GPU utilization
- Stage timings (prefill, decode, VAE decode, upsampler, total)
- Full run manifest (parameters, metrics, output video path, logs)
- Structured logs + Prometheus metrics + Grafana dashboards

Every run gets a unique `run_id` and is saved under `observability/runs/{run_id}/`.

## Quick Start

```bash
cd observability
docker compose up -d
```

Then open:
- **Grafana**: http://localhost:3000 (admin/admin) — LTX dashboard pre-loaded
- **Prometheus**: http://localhost:9090
- **Logs (Loki)**: via Grafana Explore

Run your generation scripts as usual — they are now instrumented.

## Usage in Scripts

The `generate_macos.sh` and `dfr_generate_macos.sh` have been updated (or will be) to import the observer:

```bash
python -m observability.instrument --run-id "$RUN_ID" --prompt "$PROMPT" ...
```

The Python observer starts a metrics endpoint on port 8001 and writes a rich `manifest.json` + logs after each run.

## Structure

```
observability/
├── docker-compose.yml
├── prometheus.yml
├── otel-collector-config.yaml
├── loki-config.yaml
├── instrument.py              # Core observer (prometheus + structured logs + manifest)
├── dashboards/
│   └── ltx-inference.json     # Grafana dashboard (duration, memory, logs by run_id)
├── grafana-provisioning/
│   └── datasources/
│       └── datasources.yml
└── runs/                      # Auto-created per-run manifests + logs
```

## Next Enhancements (we can add iteratively)

- Real GPU metrics via `powermetrics` parsing on Apple Silicon
- KV cache offload detection (hook into LTX logging or memory patterns)
- Automatic video metadata (duration, resolution, file hash)
- Run comparison dashboard
- Export to MLflow / Weights & Biases

Start the stack with `docker compose up -d` in the `observability/` folder and run a generation. Let me know what you see in Grafana and we'll thicken it further (deeper KV cache visibility, better Apple Silicon GPU metrics, etc.).

This gives you full traceability as you experiment with parameters, resolutions, offload strategies, and prompts.
