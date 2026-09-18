# LTX mini lab — synthesis

## Problem

Iteration 1 must generate a real mp4 from a Carbon UI, show prompt→output as a
trace, pin that run as a reference, and coexist with another local observability
stack on the same machine. The previous Gradio + bash path ignored the UI spec,
collided on common Grafana/Prometheus/Loki ports, and never traced.

## Usage (caller's view)

`./labctl up` then open the leased console URL. Generate submits a
`GenerationRequest` and watches a `Run`. `./labctl generate` uses the same
object. Callers never pass ports, venvs, or compose projects.

## Shape

`Lab` is the deep module. `VideoSpec` encodes 8k+1 frames and dims % 64.
Engines are a closed protocol (`ltx-distilled` ready now, `ltx-dfr` advertised
but blocked without LoRA, `vllm`/`sglang`/`omlx` detected not driven).
Occupancy always uses bind band 8199/8188/3300/9190/3200/5001/8001. Observability
is compose project `ltx-obs`. MLflow and Prometheus are sinks; the Run ledger
is the source of truth.

## Synthesis decision

Occupancy-namespaced Lab kernel. A second structurally distinct shape was
considered: attach LTX dashboards into an already-running foreign obs stack and
treat Run as the only public object. Grafted: Run ledger as UI source of truth,
engine `ready` flag for missing LoRA, and never-kill-by-port. Rejected: mutating
another project's Grafana provisioning; keeping Gradio.

## Tradeoffs accepted

- A second Grafana (3300) in exchange for start-order independence.
- A child-process LTX worker in exchange for an API that survives MPS OOM.
- Coarse stages (load / encode / generate / write) in exchange for not forking LTX-2.
- Vite-dev or built SPA served beside the API in exchange for shipping a live UI in iteration 1.
- Disk offload and a 9-frame proof spec so the first clip can finish under unified-memory pressure.

## Alternatives considered

- Carbon-over-Gradio: sliders still unused, occupancy still kill-by-port.
- Treating generate as an argv job map: hides process spawn, exposes the wrong noun.
- Injecting scrape jobs into a foreign compose project: couples LTX down() to that project.

## Open questions and risks

- 22B distilled + 12B text encoder is slow under disk offload; first proof uses 9 frames.
- DFR stays disabled until the gated LoRA is present.
