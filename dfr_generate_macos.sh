#!/bin/bash
# LTX-2 DFR (Production Quality) Wrapper for M1 Mac with 16GB RAM
# Uses DFRPipeline + detailing IC-LoRA for significantly better quality.
# Still heavily tuned for memory (low res, offload cpu). Expect longer runtimes.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
HF_BIN="/Users/discoposse/.local/bin/hf"
PROMPT="${1:-A serene Japanese garden at dawn with koi fish swimming in a pond, gentle mist, cinematic lighting, shallow depth of field}"
OUTPUT="${2:-output_dfr_m1.mp4}"

echo "=== LTX-2 DFR Production Generator (M1 16GB tuned) ==="
echo "Prompt: $PROMPT"
echo "Output: $OUTPUT"
echo "Resolution: 384x640 (very low for 16GB unified memory on M1)"
echo "Frames: 49 (~2s @ 24fps)"
echo "Using --offload cpu + chunked_eager VAE decode + detailing LoRA"
echo ""
echo "If it still gets Killed (OOM), the DFR stage 2 + keyframe decode is heavier."
echo "Close all other apps, or try the basic generate_macos.sh first."
echo ""

# Check for LoRA (required for DFR)
if [ ! -f "models/ltx-2.5/loras/ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors" ]; then
  echo "LoRA not found. Run this first (approve access on HF page if prompted):"
  echo "  $HF_BIN download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler \\"
  echo "    ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors \\"
  echo "    --local-dir models/ltx-2.5/loras"
  echo ""
  echo "After downloading, run this script again."
  exit 1
fi

"$VENV/bin/python" -m ltx_pipelines.dfr_pipeline \
  --transformer-path models/ltx-2.5/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors \
  --text-encoder-path models/ltx-2.5/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors \
  --video-vae-path models/ltx-2.5/vae/ltx-2.5-video-vae-bf16.safetensors \
  --audio-vae-path models/ltx-2.5/vae/ltx-2.5-audio-vae-bf16.safetensors \
  --detailing-lora models/ltx-2.5/loras/ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors \
  --spatial-upsampler-path models/ltx-2.5/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors \
  --prompt "$PROMPT" \
  --output-path "$OUTPUT" \
  --height 384 \
  --width 640 \
  --num-frames 49 \
  --frame-rate 24 \
  --seed 42 \
  --offload cpu \
  --max-batch-size 1 \
  --diffvae-optimization chunked_eager

echo ""
echo "DFR generation complete! Video saved to: $OUTPUT"
echo "This produces noticeably higher quality than the basic distilled pipeline."
echo "To change prompt: ./dfr_generate_macos.sh \"your prompt\""
