# LTX Lab

A complete macOS frontend and observability lab for LTX-2 video generation.

**Everything is now controlled from the UI.** All instructions, prompt tips, parameter guidance, MLflow tracing, and observability controls live inside the web interface.

## Quick Start

```bash
# 1. Clone and run setup (installs everything, including the webui)
git clone https://github.com/discoposse/ltx-macos-deploy.git
cd ltx-macos-deploy
./setup-ltx-macos.sh

# 2. Start the full lab (MLflow UI + Gradio frontend + observability stack)
./start-lab.sh
```

The UI will open automatically. Use the sidebar to navigate between **Generate**, **Traces**, **Observability**, **Library**, and **Info**.

All previous CLI scripts (`generate_macos.sh`, `dfr_generate_macos.sh`) still work, but the web interface is now the recommended way to work.

## Project Structure (clean & minimal)

- `start-lab.sh` — Single entry point that launches MLflow, Gradio, and the observability containers
- `webui/` — All frontend code and instructions (no more scattered READMEs)
- `setup-ltx-macos.sh` — One-time environment and model setup
- `prompts/` — Your personal prompt library (personal files are gitignored)
- `observability/` — Supporting stack (Prometheus, Grafana, Loki) — managed by the launcher
- `LTX-2/` — Official codebase (pulled and updated by setup)

All redundant launch files and duplicated documentation have been consolidated. The web UI is now the single source of truth for how to use the lab.

Happy generating — everything you need is inside the interface.
