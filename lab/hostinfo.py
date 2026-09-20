"""Host and software snapshot written next to each run for the report view."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional


LOAD_NAME = "ltx-2.5-22b-distilled"


def _sysctl(key: str) -> Optional[str]:
    try:
        out = subprocess.check_output(["sysctl", "-n", key], text=True, timeout=1)
        return out.strip() or None
    except Exception:
        return None


def capture_host(engine: str, spec: dict[str, Any], load: str = LOAD_NAME) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "captured_at": time.time(),
        "hostname": platform.node(),
        "os": platform.platform(),
        "arch": platform.machine(),
        "processor": platform.processor() or _sysctl("machdep.cpu.brand_string"),
        "hw_model": _sysctl("hw.model"),
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "python_impl": platform.python_implementation(),
        "engine": engine,
        "load": load,
        "spec": {
            "height": spec.get("height"),
            "width": spec.get("width"),
            "frames": spec.get("frames"),
            "fps": spec.get("fps"),
            "seed": spec.get("seed"),
            "offload": spec.get("offload"),
        },
    }
    try:
        import psutil

        vm = psutil.virtual_memory()
        snap["memory_bytes"] = vm.total
        snap["memory_available_bytes"] = vm.available
        snap["memory_percent"] = vm.percent
    except Exception:
        pass
    try:
        import torch

        snap["torch"] = getattr(torch, "__version__", None)
        snap["mps"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
        if snap["mps"]:
            snap["mps_allocated"] = torch.mps.current_allocated_memory()
            snap["mps_driver"] = torch.mps.driver_allocated_memory()
            snap["mps_recommended"] = torch.mps.recommended_max_memory()
    except Exception:
        snap["torch"] = None
        snap["mps"] = False
    ltx_pyproject = Path(__file__).resolve().parents[1] / "LTX-2" / "pyproject.toml"
    if ltx_pyproject.exists():
        snap["ltx_tree"] = str(ltx_pyproject.parent)
    return snap
