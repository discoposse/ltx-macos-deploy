# Session report

The Carbon **Report** page loads one lab generation and shows that session in one place: video, prompt, job, hardware, software, and charts.

## Join key

The lab `run_id` (directory name under `runs/`) is the session id. Use it everywhere:

| Surface | Where it appears |
|---|---|
| Ledger | `runs/{run_id}/run.json` |
| Video | `runs/{run_id}/output.mp4` |
| Worker log | every line starts with `run_id=` |
| Prometheus | `ltx_run_info{run_id="…"}` (identity only; histograms stay low-cardinality) |
| Loki | `{job="ltx-worker"} \|= \`run_id\`` |
| MLflow | experiment `ltx-lab`, tag `run_id`, run name = lab id |
| Grafana | dashboard `ltx-run-trace`, variable `run_id` |

Load name is `ltx-2.5-22b-distilled`. Memory and CPU gauges are process-wide; pin them to a session with the generation time window (`started_at` … `finished_at`).

## Files written per run

| File | Contents |
|---|---|
| `host.json` | Machine, OS, Python, PyTorch, MPS, spec |
| `omlx.json` | oMLX model, models dir, SSD/hot cache paths, usage, cache probe (written when oMLX is up) |
| `comfy.json` | ComfyUI URL, workflow name, prompt id, fetched artifact (Comfy engine only) |
| `comfy.workflow.json` | Filled API graph that was queued |
| `samples.jsonl` | ~5s RSS / unified / MPS / CPU samples while the worker is up |
| `worker.log` | Stage and error lines labeled with `run_id` |
| `output.mp4` | Finished clip |

The report reads these files from the ledger, so it still works if Grafana or the worker process is down. Grafana iframes are extra, for the same window.

## Grafana / Prometheus

Compose project `ltx-obs` scrapes:

- `host.docker.internal:8001` — worker (only while a generation is running)
- `host.docker.internal:8199/metrics` — lab API ledger identity

Promtail tails `runs/*/worker.log`. Open [http://127.0.0.1:3300/d/ltx-run-trace](http://127.0.0.1:3300/d/ltx-run-trace) or the Grafana / MLflow links on the report.
