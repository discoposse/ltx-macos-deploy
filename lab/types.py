from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class EngineId(str, Enum):
    ltx_distilled = "ltx-distilled"
    ltx_dfr = "ltx-dfr"
    vllm = "vllm"
    sglang = "sglang"
    omlx = "omlx"
    comfyui = "comfyui"


class Modality(str, Enum):
    video = "video"
    text = "text"


class RunState(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ReadinessState(str, Enum):
    ready = "ready"
    blocked = "blocked"
    starting = "starting"


class OccupancyError(Exception):
    """Lab refused to steal a bind or kill a foreign owner."""


class SpecError(Exception):
    """VideoSpec rejected a value that would make the vendor pipeline fail."""


class LabBusy(Exception):
    """A generation is already running."""


class EngineBlocked(Exception):
    """Requested engine is registered but not ready."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SpecError(msg)


@dataclass(frozen=True)
class IntBound:
    min: int
    max: int
    step: int

    def contains(self, value: int) -> bool:
        return self.min <= value <= self.max and (value - self.min) % self.step == 0

    def to_dict(self) -> dict[str, int]:
        return {"min": self.min, "max": self.max, "step": self.step}


@dataclass(frozen=True)
class VideoSpec:
    height: int
    width: int
    frames: int
    fps: int
    seed: int
    offload: str = "cpu"

    def __post_init__(self) -> None:
        _require(self.height > 0 and self.height % 64 == 0, "height must be a multiple of 64")
        _require(self.width > 0 and self.width % 64 == 0, "width must be a multiple of 64")
        _require(self.frames >= 9 and (self.frames - 1) % 8 == 0, "frames must be 8k+1")
        _require(self.fps > 0, "fps must be positive")
        _require(self.offload in {"cpu", "none", "disk"}, "offload is cpu|none|disk")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def with_height(self, value: int) -> "VideoSpec":
        return VideoSpec(value, self.width, self.frames, self.fps, self.seed, self.offload)

    def with_width(self, value: int) -> "VideoSpec":
        return VideoSpec(self.height, value, self.frames, self.fps, self.seed, self.offload)

    def with_frames(self, value: int) -> "VideoSpec":
        return VideoSpec(self.height, self.width, value, self.fps, self.seed, self.offload)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoSpec":
        return cls(
            height=int(data["height"]),
            width=int(data["width"]),
            frames=int(data["frames"]),
            fps=int(data.get("fps", 24)),
            seed=int(data.get("seed", 42)),
            offload=str(data.get("offload", "cpu")),
        )

    @classmethod
    def capture(
        cls,
        height: Any = None,
        width: Any = None,
        frames: Any = None,
        fps: Any = None,
        seed: Any = None,
        offload: Any = None,
    ) -> "VideoSpec":
        """Best-effort spec from a Comfy graph (may snap to LTX-legal multiples)."""

        def _int(value: Any, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        h = max(64, _int(height, 256))
        h -= h % 64
        w = max(64, _int(width, 384))
        w -= w % 64
        f = _int(frames, 9)
        if f < 9:
            f = 9
        else:
            f = 1 + 8 * max(1, round((f - 1) / 8.0))
        rate = max(1, _int(fps, 24))
        mode = str(offload or "disk")
        if mode not in {"cpu", "none", "disk"}:
            mode = "disk"
        return cls(h, w, f, rate, _int(seed, 42), mode)


PROOF_SPEC = VideoSpec(height=256, width=384, frames=9, fps=24, seed=42, offload="disk")
DEFAULT_SPEC = VideoSpec(height=256, width=384, frames=9, fps=24, seed=42, offload="disk")


@dataclass(frozen=True)
class VideoBounds:
    height: IntBound
    width: IntBound
    frames: IntBound

    def to_dict(self) -> dict[str, Any]:
        return {
            "height": self.height.to_dict(),
            "width": self.width.to_dict(),
            "frames": self.frames.to_dict(),
        }


LTX_VIDEO_BOUNDS = VideoBounds(
    height=IntBound(256, 768, 64),
    width=IntBound(256, 1280, 64),
    frames=IntBound(9, 193, 8),
)


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    engine: EngineId
    spec: VideoSpec
    label: Optional[str] = None
    workflow: Optional[str] = None

    def __post_init__(self) -> None:
        _require(bool(self.prompt.strip()), "prompt is required")
        _require(len(self.prompt) <= 4000, "prompt too long")

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "engine": self.engine.value,
            "spec": self.spec.to_dict(),
            "label": self.label,
            "workflow": self.workflow,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationRequest":
        engine = data.get("engine", EngineId.ltx_distilled.value)
        return cls(
            prompt=str(data.get("prompt", "")),
            engine=EngineId(engine),
            spec=VideoSpec.from_dict(data.get("spec") or data),
            label=data.get("label"),
            workflow=str(data["workflow"]) if data.get("workflow") else None,
        )


@dataclass(frozen=True)
class EngineProfile:
    id: EngineId
    label: str
    modality: Modality
    ready: bool
    blocked_reason: Optional[str]
    bounds: Optional[VideoBounds]
    default_spec: Optional[VideoSpec]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id.value,
            "label": self.label,
            "modality": self.modality.value,
            "ready": self.ready,
            "blocked_reason": self.blocked_reason,
            "bounds": None if self.bounds is None else self.bounds.to_dict(),
            "default_spec": None if self.default_spec is None else self.default_spec.to_dict(),
        }


@dataclass(frozen=True)
class Artifact:
    kind: str
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Stage:
    name: str
    label: str
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        duration = None
        if self.started_at is not None and self.ended_at is not None:
            duration = round(self.ended_at - self.started_at, 2)
        return {
            "name": self.name,
            "label": self.label,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "duration_s": duration,
            "duration_label": "" if duration is None else f"{duration:.1f}s",
        }


@dataclass
class RunTrace:
    run_id: str
    mlflow_run_id: Optional[str] = None
    mlflow_experiment_id: Optional[str] = None
    stages: list[Stage] = field(default_factory=list)
    current_index: int = 0
    events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mlflow_run_id": self.mlflow_run_id,
            "mlflow_experiment_id": self.mlflow_experiment_id,
            "stages": [s.to_dict() for s in self.stages],
            "current_index": self.current_index,
            "events": self.events[-200:],
        }


@dataclass
class Run:
    id: str
    request: GenerationRequest
    state: RunState
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    trace: RunTrace = field(default_factory=lambda: RunTrace(run_id=""))
    artifact: Optional[Artifact] = None
    error: Optional[str] = None
    pid: Optional[int] = None
    pinned: bool = False

    def is_terminal(self) -> bool:
        return self.state in {RunState.succeeded, RunState.failed, RunState.cancelled}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request": self.request.to_dict(),
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "trace": self.trace.to_dict(),
            "artifact": None if self.artifact is None else self.artifact.to_dict(),
            "error": self.error,
            "pid": self.pid,
            "pinned": self.pinned,
        }


@dataclass(frozen=True)
class ReferencePin:
    id: str
    run_id: str
    label: str
    pinned_at: float
    request: GenerationRequest
    artifact: Artifact
    trace: RunTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "label": self.label,
            "pinned_at": self.pinned_at,
            "request": self.request.to_dict(),
            "artifact": self.artifact.to_dict(),
            "trace": self.trace.to_dict(),
        }


@dataclass(frozen=True)
class Component:
    id: str
    label: str
    kind: str
    state: str
    required: bool
    detail: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LabLinks:
    console: str
    grafana: str
    prometheus: str
    mlflow: str
    metrics: str
    loki: str
    omlx: str = "http://127.0.0.1:8000/admin"
    comfy: str = "http://127.0.0.1:8189"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OccupancyView:
    band: str
    attached_neighbors: tuple[str, ...]
    exclusive: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "attached_neighbors": list(self.attached_neighbors),
            "exclusive": self.exclusive,
        }


@dataclass
class Readiness:
    state: ReadinessState
    checked_at: float
    components: list[Component]
    occupancy: OccupancyView
    links: LabLinks
    engines: list[EngineProfile] = field(default_factory=list)

    def blockers(self) -> list[Component]:
        return [c for c in self.components if c.required and c.state != "up"]

    def to_dict(self) -> dict[str, Any]:
        blockers = self.blockers()
        return {
            "state": self.state.value,
            "checked_at": self.checked_at,
            "summary": {
                "up": sum(1 for c in self.components if c.state == "up"),
                "total": len(self.components),
                "required_down": len(blockers),
            },
            "components": [c.to_dict() for c in self.components],
            "occupancy": self.occupancy.to_dict(),
            "links": self.links.to_dict(),
            "engines": [e.to_dict() for e in self.engines],
        }


@dataclass(frozen=True)
class LabAction:
    id: str
    title: str
    group: str
    confirm: bool
    warning: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ROOT = Path(__file__).resolve().parents[1]
LTX_ROOT = ROOT / "LTX-2"
RUNS_DIR = ROOT / "runs"
REFS_DIR = ROOT / "references"
LEASE_PATH = ROOT / ".lab" / "lease.json"
PIDS_PATH = ROOT / ".lab" / "pids.json"
CONSOLE_DIST = ROOT / "lab-console" / "dist"

LTX_BAND = {
    "lab_api": 8199,
    "console": 8188,
    "grafana": 3300,
    "prometheus": 9190,
    "loki": 3200,
    "mlflow": 5001,
    "metrics": 8001,
    "otel_grpc": 14317,
    "otel_http": 14318,
}

# Binds this lab must never take, even if the LTX band is later remapped.
FOREIGN_PORTS = {
    3000: "infinia-grafana",
    9090: "infinia-prometheus",
    3100: "infinia-loki",
    9093: "infinia-alertmanager",
    9115: "infinia-blackbox",
    8088: "infinia-lab-console",
    8099: "infinia-lab-api",
    8100: "infinia-vllm",
    8096: "infinia-lmcache-metrics",
    5555: "infinia-lmcache",
    5000: "macos-control-center",
}

INFINIA_CONTAINERS = (
    "infinia-grafana",
    "infinia-prometheus",
    "infinia-loki",
    "infinia-promtail",
    "infinia-alertmanager",
    "infinia-blackbox",
    "infinia-lab-console",
)

DEFAULT_PROMPT = (
    "A red hatchback dropped from a helicopter onto a windy coastal runway, "
    "cinematic lighting, shallow depth of field, 24fps"
)

# Queued generations waiting behind the current worker. One worker at a time.
MAX_QUEUE = 8
