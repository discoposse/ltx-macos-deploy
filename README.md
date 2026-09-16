# LTX-2 macOS Deployment (Private Repo)

This repository contains **only** our deployment, setup, and prompt workflow for running LTX-2 on Apple Silicon (M1/M2/M3/M4).

It does **not** contain the full LTX source tree — it pulls what it needs from the official repo during setup.

## Quick Start

```bash
# 1. Run the setup (downloads models ~66GB, creates venv, installs our scripts)
curl -O https://raw.githubusercontent.com/yourusername/ltx-macos-deploy/main/setup-ltx-macos.sh
chmod +x setup-ltx-macos.sh
./setup-ltx-macos.sh
```

## Usage

```bash
cd LTX-2

# Fast generation (recommended for 16GB RAM)
./generate_macos.sh "A serene Japanese garden at dawn with koi fish swimming in a pond, gentle mist, cinematic lighting"

# Production quality (DFR + detailing LoRA)
./dfr_generate_macos.sh "Same prompt here"
```

You can pass a second argument for custom output filename:

```bash
./generate_macos.sh "your prompt" my-cool-video.mp4
```

## Files

- `setup-ltx-macos.sh` — One-command setup (models + venv + our scripts)
- `generate_macos.sh` — Tuned DistilledPipeline for M1 16GB (384x640, offload cpu, chunked_eager)
- `dfr_generate_macos.sh` — DFR production pipeline (needs the IC-LoRA)
- `prompts/` — (add this folder) — store your prompt library, experiments, etc.

## Philosophy

- Keep this repo **clean** and focused on deployment, prompts, and our custom wrappers.
- Never commit the full `packages/` or large model files.
- The setup script pulls the official LTX-2 code and models on first run.

This gives you a private, shareable, reproducible workflow separate from the main LTX-2 repository.

Happy generating!
