#!/bin/bash
# LTX-2 Mac Setup Script
# One-command initial setup for a new machine (M1/M2/M3/M4 with 16GB+ RAM)
# Creates a clean environment with our tuned generation wrappers.
# Does NOT include the full LTX source tree — only the runtime pieces we need.

set -e

echo "=== LTX-2 Mac Setup (M1 16GB tuned) ==="
echo "This will create a minimal runtime environment with our custom scripts."
echo ""

# 1. Clone or update the official repo (we need the packages for inference)
if [ ! -d "LTX-2" ]; then
  echo "Cloning official LTX-2 repository..."
  git clone https://github.com/Lightricks/LTX-2.git
  cd LTX-2
else
  echo "LTX-2 directory already exists, updating..."
  cd LTX-2
  git pull
fi

# 2. Create virtual environment and install dependencies
echo "Creating virtual environment and installing dependencies..."
# The official LTX-2 repo does not commit uv.lock (it's gitignored).
# On a fresh clone we must generate it first. --frozen then works reliably.
if [ ! -f "uv.lock" ]; then
  echo "No uv.lock found (fresh clone). Running uv lock..."
  uv lock
fi
uv sync --frozen

# 3. Download the required model weights (split layout for LTX-2.5 distilled)
echo "Downloading model weights (this may take a while, ~66GB total)..."
mkdir -p models/ltx-2.5/loras

hf download Lightricks/LTX-2.5 \
  diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors \
  text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors \
  vae/ltx-2.5-video-vae-bf16.safetensors \
  vae/ltx-2.5-audio-vae-bf16.safetensors \
  latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors \
  --local-dir models/ltx-2.5

# 4. Download the detailing LoRA for DFR (production quality) — requires approval on HF
echo ""
echo "Downloading IC-LoRA for DFR (you may need to approve access on Hugging Face)..."
hf download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler \
  ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors \
  --local-dir models/ltx-2.5/loras || echo "LoRA download skipped (approve on HF if needed)."

# 5. Copy our tuned wrapper scripts
echo "Installing our custom macOS-tuned generation scripts..."
cp ../generate_macos.sh .
cp ../dfr_generate_macos.sh .
chmod +x generate_macos.sh dfr_generate_macos.sh

echo ""
echo "=== Setup Complete! ==="
echo "To generate video:"
echo "  cd LTX-2"
echo "  ./generate_macos.sh \"your prompt here\""
echo ""
echo "For higher quality (once LoRA is downloaded):"
echo "  ./dfr_generate_macos.sh \"your prompt here\""
echo ""
echo "Next steps for your private repo:"
echo "1. Create a new private GitHub repo (e.g. ltx-macos-deploy)"
echo "2. Copy this setup-ltx-macos.sh, generate_macos.sh, dfr_generate_macos.sh, and prompts/ folder into it"
echo "3. Add a README with usage instructions"
echo "4. git init, commit, and push — this repo will stay clean of the full LTX source."
echo ""
echo "You now have a reproducible deployment flow separate from the main LTX-2 codebase."
