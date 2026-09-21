# LTX Lab

Local video generation with LTX-2 distilled, a Carbon console, a run ledger, MLflow traces, and a dedicated Grafana/Prometheus/Loki stack.

This repository is the **lab kit**. It does not contain LTX-2 source or model weights.

```bash
./setup-ltx-macos.sh
./labctl up
open http://127.0.0.1:8188
```

Tester walkthrough: [docs/TESTING.md](docs/TESTING.md). Session report: [docs/OBSERVE.md](docs/OBSERVE.md). oMLX prompt rewrite: [docs/OMLX.md](docs/OMLX.md). Licenses: [LICENSE](LICENSE), [NOTICE](NOTICE), [docs/LICENSES.md](docs/LICENSES.md).

## Generate

On **Generate**, run one clip at a time. Defaults are a short proof (256×384, 9 frames, disk offload) so the first video can finish on a loaded Mac. **Report** loads that session’s video, prompt, job, host, and charts. **Pin as reference** copies the clip into `references/`.

```bash
./labctl status
./labctl generate --smoke --wait "a red hatchback on a coastal runway"
./labctl pin <run-id> --label first-clip
./labctl url grafana
```

## Ports

| Surface | Port |
|---|---|
| Carbon console | 8188 |
| Lab API | 8199 |
| Grafana | 3300 |
| Prometheus | 9190 |
| Loki | 3200 |
| MLflow | 5001 |
| Worker metrics | 8001 |
| oMLX (neighbor) | 8000 |
| ComfyUI (neighbor) | 8189 |

The lab will not bind a port that is already taken and will not `docker compose down` a foreign project. `./labctl down` stops only this lab. It never starts oMLX or ComfyUI.

## Engines

**LTX-2 distilled** is the default video engine. **LTX-2 DFR** is available when the gated IC-LoRA is on disk; it is slower and hungrier than distilled, so keep the first clip on the 9-frame proof spec with disk offload. **ComfyUI** is an optional local graph engine. Run `./labctl comfy start` (clones `~/Documents/ComfyUI` if needed and listens on `:8189`; this lab already owns `:8188`). Export the LTX graph with File → Export (API) into `workflows/comfy/`, then pick **ComfyUI (local graph)** on Generate. **oMLX** is a separate local LLM on `:8000`. Load the model and set SSD/hot cache in the oMLX admin, then use **Rewrite with oMLX** on Generate (or `./labctl omlx rewrite`). The next Report shows those cache paths. See [docs/OMLX.md](docs/OMLX.md). vLLM and SGLang are still detection-only.

## Layout

- `lab/` — occupancy, run ledger, worker, HTTP API
- `lab-console/` — Carbon SPA
- `observability/` — compose project `ltx-obs`
- `LTX-2/` — vendor clone + weights (gitignored)
- `runs/` — per-run mp4, log, status (gitignored)
- `references/` — pinned proofs (gitignored)
- `workflows/comfy/` — ComfyUI API-format exports (your JSON stays gitignored)

## License

Original source in this repository is **MIT**. Running the lab downloads LTX-2.5 under the **LTX-2.x Community License** (Lightricks). Organizations at or above the revenue threshold in that license may need a paid commercial grant. Details in [docs/LICENSES.md](docs/LICENSES.md).
