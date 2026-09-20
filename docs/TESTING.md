# Tester guide

Goal: clone this repo, generate one clip from the web UI, watch the run, pin it.

## Requirements

- macOS on Apple Silicon
- Roughly 64GB unified memory (22B distilled + 12B text encoder)
- Docker Desktop
- [uv](https://docs.astral.sh/uv/)
- Hugging Face CLI (`hf`) and a login that can download `Lightricks/LTX-2.5`
- Python 3.12+

Weights are about 66GB. First setup is a long download.

## License gate

Setup clones [Lightricks/LTX-2](https://github.com/Lightricks/LTX-2) and downloads LTX-2.5 distilled weights. That is **not** MIT. Read [LICENSES.md](LICENSES.md) and [third_party/LTX-2.x-Community-License.txt](../third_party/LTX-2.x-Community-License.txt) first.

```bash
huggingface-cli login
```

## Setup

```bash
git clone https://github.com/discoposse/ltx-macos-deploy.git
cd ltx-macos-deploy
./setup-ltx-macos.sh
./labctl up
open http://127.0.0.1:8188
```

`labctl up` starts the lab API, Carbon console, MLflow, and compose project `ltx-obs`. It binds a private port band and will refuse to steal a port that is already taken.

| Surface | URL |
|---|---|
| Console | http://127.0.0.1:8188 |
| Lab API | http://127.0.0.1:8199 |
| Grafana | http://127.0.0.1:3300 |
| Prometheus | http://127.0.0.1:9190 |
| Loki | http://127.0.0.1:3200 |
| MLflow | http://127.0.0.1:5001 |

## First clip

On **Generate**:

1. Leave the default spec (256×384, 9 frames, disk offload). That is the size that has completed on a loaded machine.
2. Use any lawful prompt.
3. Click **Generate**. Expect on the order of **8–15 minutes** for the first success (disk offload rereads weights each denoise step).
4. When the player appears, click **Pin as reference**.
5. Open **Report** for the clip, prompt, job, host, and charts. **Library** holds pins.

CLI equivalent:

```bash
./labctl generate --smoke --wait "a red hatchback on a coastal runway"
./labctl pin <run-id> --label first-clip
```

`--smoke` uses the same 9-frame proof spec.

## Pass / fail

Pass:

- Status shows the lab ready (weights, venv, API, console, Grafana, Prometheus).
- Generate writes `runs/<id>/output.mp4` (H.264, audio optional).
- Report shows the mp4, prompt, job details, and stage timings. New runs also store `host.json` and `samples.jsonl` for memory/CPU charts.
- Pin appears in Library.
- MLflow has an `ltx-lab` experiment run.
- `./labctl down` stops this lab only.

Fail:

- Missing distilled weights. DFR also needs `LTX-2/models/ltx-2.5/loras/ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors` (gated Hugging Face repo; accept access, then download with `HF_TOKEN`).
- AUTO tiling / OOM on larger sliders — drop back to 9 frames and disk offload.
- Port already bound — stop the leftover LTX process, do not kill foreign compose projects.

## Larger clips

Sliders go up to 768×1280 and 193 frames (~8s at 24fps). That is slower and more likely to exhaust unified memory. Prove 9 frames first, then 97, then 193.

## oMLX (optional prompt rewrite)

oMLX is not required for video. If it is running on `http://127.0.0.1:8000`, Generate shows **Rewrite with oMLX**. Details: [OMLX.md](OMLX.md).

```bash
omlx start
./labctl omlx
./labctl omlx rewrite "a red hatchback on a coastal runway"
```

## Stop

```bash
./labctl down
```
