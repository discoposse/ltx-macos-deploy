# LTX-2 observability stack

Compose project **`ltx-obs`**. Host ports default to the LTX bind band so this
stack can sit next to another Grafana/Prometheus/Loki install.

| Service | Host port |
|---|---|
| Grafana | 3300 |
| Prometheus | 9190 |
| Loki | 3200 |
| OTLP gRPC/HTTP | 14317 / 14318 |

Do not publish 3000/9090/3100 from this compose file. `./labctl up` starts this
project; `./labctl down` stops only `ltx-obs`.

Dashboards (folder **LTX Lab**): overview, inference, host, run-trace, queries.

The Python observer (`instrument.py`) is a sink used by `lab.worker`. The Run
ledger under `runs/{id}/` is the source of truth the Carbon **Report** page reads
(`host.json`, `samples.jsonl`, `worker.log`, `output.mp4`). Join key is lab
`run_id`. See [docs/OBSERVE.md](../docs/OBSERVE.md).

Grafana and Loki images are AGPL-3.0; Prometheus and the OpenTelemetry Collector
are Apache-2.0. See [docs/LICENSES.md](../docs/LICENSES.md).
