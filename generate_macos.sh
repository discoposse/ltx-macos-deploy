#!/bin/bash
# LTX-2 Video Generation Wrapper for M1 Mac with 16GB RAM
# Tuned for memory constraints: low resolution, heavy CPU offload, small number of frames.
# Uses the fast DistilledPipeline (recommended starting point).

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
HF_BIN="${HF_BIN:-$(command -v hf || true)}"
PROMPT="${1:-a big truck being dropped from a helicopter onto an island beach}"
OUTPUT="${2:-output_m1.mp4}"

echo "=== LTX-2 Video Generator (M1 16GB tuned) ==="
echo "Prompt: $PROMPT"
echo "Output: $OUTPUT"
echo "Resolution: 384x640 (very low for 16GB unified memory on M1)"
echo "Frames: 200 (~2s @ 24fps)"
echo "Using --offload cpu + chunked_eager VAE decode"
echo ""
echo "If it still gets Killed (OOM), try even smaller: --height 320 --width 512 or close other apps."
echo "MPS on M1 with 16GB is very constrained for this 22B model."
echo ""

# Ensure models are present
if [ ! -f "models/ltx-2.5/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors" ]; then
  echo "Error: Models not found. Run the download commands from the README first."
  exit 1
fi

"$VENV/bin/python" -m ltx_pipelines.distilled \
  --transformer-path models/ltx-2.5/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors \
  --text-encoder-path models/ltx-2.5/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors \
  --video-vae-path models/ltx-2.5/vae/ltx-2.5-video-vae-bf16.safetensors \
  --audio-vae-path models/ltx-2.5/vae/ltx-2.5-audio-vae-bf16.safetensors \
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
echo "Generation complete! Video saved to: $OUTPUT"
echo "To try a different prompt: ./generate_macos.sh \"your new prompt here\""
echo "For higher quality (slower), use ./dfr_generate_macos.sh after approving the LoRA repo on Hugging Face."
