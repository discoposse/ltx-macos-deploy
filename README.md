# LTX-2 macOS Deployment Kit

This repository is a lightweight, reproducible setup for running LTX-2 video generation on Apple Silicon Macs (M1/M2/M3/M4 with 16 GB or more RAM).

It contains only the files needed for easy deployment:
- A one-command setup script
- Tuned wrapper scripts optimized for Mac memory and performance
- A prompts folder for your own creative work

The full LTX-2 codebase and model weights (~66 GB) are pulled from the official repository during setup. This keeps the project small and focused on the macOS workflow.

## Quick Start

1. Clone the repo:
   ```bash
   git clone https://github.com/discoposse/ltx-macos-deploy.git
   cd ltx-macos-deploy
   ```

2. Run the setup:
   ```bash
   ./setup-ltx-macos.sh
   ```

## Usage

After setup, generate videos from the LTX-2 directory:

```bash
cd LTX-2

# Fast generation (recommended for 16 GB RAM)
./generate_macos.sh "A serene Japanese garden at dawn with koi fish swimming in the pond, gentle mist, cinematic lighting"

# Higher quality (DFR with detailing LoRA)
./dfr_generate_macos.sh "Same prompt here"
```

You can supply a custom output filename as the second argument:

```bash
./generate_macos.sh "your prompt" my-video.mp4
```

## Updating

To get the latest scripts and improvements:

```bash
git pull
```

Re-run `./setup-ltx-macos.sh` if the environment or wrappers have changed.

## Prompts and Your Own Work

The `prompts/` folder is the place for your prompt library, experiments, and any custom generation scripts you create.

**Do not commit your personal prompts or custom scripts to git.**  
Add patterns like `prompts/*.txt` (except the sample files) or your own scripts to `.gitignore`. This keeps the repository clean while giving you a convenient place to store the work you build over time.

The few sample prompts included are just starting points.

## What's Included

- `setup-ltx-macos.sh` — Clones/updates LTX-2, sets up the virtual environment, installs dependencies, and installs the tuned wrappers
- `generate_macos.sh` — Memory-tuned distilled pipeline (CPU offload, low resolution, chunked VAE decode)
- `dfr_generate_macos.sh` — Production DFR pipeline with detailing IC-LoRA (requires the extra LoRA download)
- `prompts/` — Your prompt collection (keep personal files untracked)
- `observability/` — Optional monitoring setup (Prometheus/Grafana)

This kit gives you a clean, repeatable macOS deployment that stays separate from the upstream LTX-2 codebase.

Happy generating.
