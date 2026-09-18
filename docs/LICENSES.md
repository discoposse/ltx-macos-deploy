# Licenses

| Piece | License | Where |
|---|---|---|
| This lab (API, console, compose, scripts) | MIT | [LICENSE](../LICENSE) |
| Carbon Design System | Apache-2.0 | npm `@carbon/react` |
| LTX-2.x code + LTX-2.5 weights | LTX-2.x Community License | Cloned at setup; copy in [third_party/LTX-2.x-Community-License.txt](../third_party/LTX-2.x-Community-License.txt) |
| Grafana, Loki | AGPL-3.0 | Docker images |
| Prometheus, OpenTelemetry Collector, MLflow | Apache-2.0 | Docker images / venv |

This git repo does **not** include LTX-2 source or model weights. Those stay on the machine that runs `./setup-ltx-macos.sh`.

## What a tester must accept

1. MIT for this kit.
2. The Lightricks **LTX-2.x Community License** and [Acceptable Use Policy](https://static.lightricks.com/legal/ltx-acceptable-use-policy.pdf) before cloning LTX-2 or downloading weights.
3. Hugging Face terms for `Lightricks/LTX-2.5`.

If your organization has annual revenue of **USD 10M or more**, read section 2 of the LTX-2.x Community License. Paid commercial use may be required except for a Non-Commercial Purpose as defined there.

## What we do not ship

- `LTX-2/` vendor tree
- `*.safetensors` weights (~66GB)
- `runs/` and `references/` outputs
- MLflow sqlite databases
