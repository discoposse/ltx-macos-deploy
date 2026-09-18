# LTX Lab

Local video generation with LTX-2 distilled, a Carbon console, a run ledger, MLflow traces, and a dedicated Grafana/Prometheus/Loki stack.

This repository is the **lab kit**. It does not contain LTX-2 source or model weights.

```bash
./setup-ltx-macos.sh
./labctl up
open http://127.0.0.1:8188
```

Tester walkthrough: [docs/TESTING.md](docs/TESTING.md). Licenses: [LICENSE](LICENSE), [NOTICE](NOTICE), [docs/LICENSES.md](docs/LICENSES.md).

## Generate

On **Generate**, run one clip at a time. Defaults are a short proof (256×384, 9 frames, disk offload) so the first video can finish on a loaded Mac. **Observe** follows prompt → stages → mp4. **Pin as reference** copies the clip into `references/`.

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

The lab will not bind a port that is already taken and will not `docker compose down` a foreign project. `./labctl down` stops only this lab.

## Engines

Iteration 1 generates video with **LTX-2 distilled**. DFR is listed but blocked until the gated IC-LoRA is present. vLLM, SGLang, and oMLX are detected when those servers are already running; they are not generation backends yet.

## Layout

- `lab/` — occupancy, run ledger, worker, HTTP API
- `lab-console/` — Carbon SPA
- `observability/` — compose project `ltx-obs`
- `LTX-2/` — vendor clone + weights (gitignored)
- `runs/` — per-run mp4, log, status (gitignored)
- `references/` — pinned proofs (gitignored)

## License

Original source in this repository is **MIT**. Running the lab downloads LTX-2.5 under the **LTX-2.x Community License** (Lightricks). Organizations at or above the revenue threshold in that license may need a paid commercial grant. Details in [docs/LICENSES.md](docs/LICENSES.md).
