from __future__ import annotations

import json
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from lab.types import (
    FOREIGN_PORTS,
    INFINIA_CONTAINERS,
    LTX_BAND,
    LTX_ROOT,
    ROOT,
    EngineId,
    EngineProfile,
    Modality,
    OccupancyError,
    OccupancyView,
    LTX_VIDEO_BOUNDS,
    DEFAULT_SPEC,
)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def http_ok(url: str, timeout: float = 1.2) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200).decode("utf-8", "replace")
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return True, f"HTTP {exc.code} (auth, reachable)"
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def docker_names() -> set[str]:
    if not shutil.which("docker"):
        return set()
    try:
        out = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            text=True,
            timeout=8,
        )
        return {line.strip() for line in out.splitlines() if line.strip()}
    except Exception:
        return set()


def neighbors() -> tuple[str, ...]:
    names = docker_names()
    found = [n for n in INFINIA_CONTAINERS if n in names]
    if port_open(8099):
        found.append("infinia-lab-api")
    if port_open(8100):
        found.append("vllm :8100")
    if port_open(8000):
        found.append("omlx :8000")
    return tuple(dict.fromkeys(found))


def assert_band_free_or_self(lease: Optional[dict[str, Any]] = None) -> None:
    for name, port in LTX_BAND.items():
        if not port_open(port):
            continue
        if lease and int(lease.get("ports", {}).get(name, -1)) == port:
            continue
        owner = FOREIGN_PORTS.get(port, "foreign")
        raise OccupancyError(
            f"LTX bind {name}:{port} is already taken ({owner}). "
            "Refusing to steal. Stop the leftover LTX process or choose another host."
        )
    for port, owner in FOREIGN_PORTS.items():
        # Informational only — we never bind these.
        _ = (port, owner)


def write_lease(ports: dict[str, int], pid: int) -> dict[str, Any]:
    payload = {
        "band": "ltx-81xx",
        "pid": pid,
        "ports": ports,
        "compose_project": "ltx-obs",
        "neighbors": list(neighbors()),
    }
    path = ROOT / ".lab" / "lease.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return payload


def read_lease() -> Optional[dict[str, Any]]:
    path = ROOT / ".lab" / "lease.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def occupancy_view(exclusive: bool) -> OccupancyView:
    return OccupancyView(
        band="ltx-81xx",
        attached_neighbors=neighbors(),
        exclusive=exclusive,
    )


def detect_engines() -> list[EngineProfile]:
    distilled = LTX_ROOT / "models/ltx-2.5/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors"
    text = LTX_ROOT / "models/ltx-2.5/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"
    video_vae = LTX_ROOT / "models/ltx-2.5/vae/ltx-2.5-video-vae-bf16.safetensors"
    audio_vae = LTX_ROOT / "models/ltx-2.5/vae/ltx-2.5-audio-vae-bf16.safetensors"
    upsampler = LTX_ROOT / "models/ltx-2.5/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"
    lora = LTX_ROOT / "models/ltx-2.5/loras/ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors"
    venv_python = LTX_ROOT / ".venv/bin/python"

    missing_distilled = [
        p.name
        for p in (distilled, text, video_vae, audio_vae, upsampler, venv_python)
        if not p.exists()
    ]
    distilled_ready = not missing_distilled

    vllm_ok, vllm_detail = http_ok("http://127.0.0.1:8100/v1/models")
    omlx_ok, omlx_detail = http_ok("http://127.0.0.1:8000/health")
    if not omlx_ok:
        omlx_ok, omlx_detail = http_ok("http://127.0.0.1:8000/v1/models")
    sglang_ok, sglang_detail = http_ok("http://127.0.0.1:30000/v1/models")

    return [
        EngineProfile(
            id=EngineId.ltx_distilled,
            label="LTX-2 Distilled (local video)",
            modality=Modality.video,
            ready=distilled_ready,
            blocked_reason=None if distilled_ready else f"Missing: {', '.join(missing_distilled)}",
            bounds=LTX_VIDEO_BOUNDS,
            default_spec=DEFAULT_SPEC,
        ),
        EngineProfile(
            id=EngineId.ltx_dfr,
            label="LTX-2 DFR (high quality)",
            modality=Modality.video,
            ready=distilled_ready and lora.exists(),
            blocked_reason=None
            if distilled_ready and lora.exists()
            else "DFR LoRA not downloaded (gated Hugging Face repo)",
            bounds=LTX_VIDEO_BOUNDS,
            default_spec=DEFAULT_SPEC,
        ),
        EngineProfile(
            id=EngineId.vllm,
            label="vLLM (detected, later swap)",
            modality=Modality.text,
            ready=vllm_ok,
            blocked_reason=None if vllm_ok else vllm_detail,
            bounds=None,
            default_spec=None,
        ),
        EngineProfile(
            id=EngineId.sglang,
            label="SGLang (detected, later swap)",
            modality=Modality.text,
            ready=sglang_ok,
            blocked_reason=None if sglang_ok else sglang_detail,
            bounds=None,
            default_spec=None,
        ),
        EngineProfile(
            id=EngineId.omlx,
            label="oMLX (detected, later swap)",
            modality=Modality.text,
            ready=omlx_ok,
            blocked_reason=None if omlx_ok else omlx_detail,
            bounds=None,
            default_spec=None,
        ),
    ]


def weight_paths() -> dict[str, Path]:
    base = LTX_ROOT / "models/ltx-2.5"
    return {
        "transformer": base / "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
        "text_encoder": base / "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "video_vae": base / "vae/ltx-2.5-video-vae-bf16.safetensors",
        "audio_vae": base / "vae/ltx-2.5-audio-vae-bf16.safetensors",
        "upsampler": base / "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        "lora": base / "loras/ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors",
    }
