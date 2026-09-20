"""Worker-side Prometheus gauges, histograms, and structured log lines.

The lab run id (not a random uuid) is the join key for Grafana, Loki, and MLflow.
High-cardinality identity lives on an Info metric and in logs, not on every histogram.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from prometheus_client import Counter, Gauge, Histogram, Info

from lab.hostinfo import LOAD_NAME

logger = logging.getLogger("ltx-obs")

run_counter = Counter("ltx_runs_total", "LTX generations started", ["engine", "offload"])
run_finished = Counter("ltx_runs_finished_total", "LTX generations finished", ["engine", "offload", "status"])
duration_histogram = Histogram(
    "ltx_duration_seconds",
    "Stage wall time",
    ["stage", "engine", "offload"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 900, 1800),
)
memory_gauge = Gauge("ltx_memory_bytes", "Worker memory", ["type"])
cpu_gauge = Gauge("ltx_cpu_percent", "Worker process CPU percent")
gpu_util_gauge = Gauge("ltx_gpu_utilization_percent", "GPU util if available")
stage_running = Gauge("ltx_stage_running", "1 while a named stage is in progress", ["stage"])
frames_gauge = Gauge("ltx_spec_frames", "Frame count of the active or last run")
pixels_gauge = Gauge("ltx_spec_pixels", "height*width of the active or last run")
video_bytes_gauge = Gauge("ltx_video_bytes", "output.mp4 size of the last succeeded run")
run_active = Gauge("ltx_run_active", "1 while a generation is running")
run_info = Info("ltx_run", "Identity of the active or last generation")


def _safe(value: Any, limit: int = 120) -> str:
    text = str(value or "").replace("\\", "/").replace('"', "")
    return text[:limit] or "none"


def spec_label(spec: dict[str, Any]) -> str:
    return f"{spec.get('height')}x{spec.get('width')}x{spec.get('frames')}"


def video_name(path: str, run_id: str) -> str:
    if path:
        return Path(path).name
    return "output.mp4"


@dataclass
class RunManifest:
    run_id: str
    timestamp: str
    prompt: str
    pipeline: str
    parameters: dict
    metrics: dict
    output_video: str
    load: str = LOAD_NAME
    mlflow_run_id: str = ""
    status: str = "running"
    notes: str = ""
    events: list[str] = field(default_factory=list)


class LTXObserver:
    def __init__(
        self,
        run_id: str,
        engine: str = "ltx-distilled",
        spec: Optional[dict[str, Any]] = None,
        mlflow_run_id: str = "",
        prompt: str = "",
        dest: Optional[Path] = None,
        load: str = LOAD_NAME,
    ) -> None:
        spec = spec or {}
        self.run_id = run_id
        self.engine = engine
        self.load = load or LOAD_NAME
        self.spec = spec
        self.mlflow_run_id = mlflow_run_id or ""
        self.offload = str(spec.get("offload") or "disk")
        self.start_time = time.time()
        self.stage_starts: dict[str, float] = {}
        self.current_stage: Optional[str] = None
        self._sampling = False
        self._sampler: Optional[threading.Thread] = None
        self.dest = Path(dest) if dest else Path("runs") / run_id
        self.dest.mkdir(parents=True, exist_ok=True)
        self.samples_path = self.dest / "samples.jsonl"
        self._sample_lock = threading.Lock()
        self.manifest = RunManifest(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            prompt=(prompt[:200] + "…") if len(prompt) > 200 else prompt,
            pipeline=engine,
            parameters=spec,
            metrics={},
            output_video="",
            mlflow_run_id=self.mlflow_run_id,
        )
        self._publish_info("")

    def _labels(self) -> dict[str, str]:
        return {
            "run_id": _safe(self.run_id, 40),
            "engine": _safe(self.engine, 40),
            "offload": _safe(self.offload, 16),
            "load": _safe(self.load, 40),
            "spec": _safe(spec_label(self.spec), 32),
            "video": _safe(video_name(self.manifest.output_video, self.run_id), 64),
            "mlflow_run_id": _safe(self.mlflow_run_id, 40),
            "height": _safe(self.spec.get("height"), 8),
            "width": _safe(self.spec.get("width"), 8),
            "frames": _safe(self.spec.get("frames"), 8),
        }

    def _publish_info(self, video: str) -> None:
        if video:
            self.manifest.output_video = video
        run_info.info(self._labels())
        frames_gauge.set(float(self.spec.get("frames") or 0))
        pixels_gauge.set(float(self.spec.get("height") or 0) * float(self.spec.get("width") or 0))

    def log(self, event: str, **fields: Any) -> None:
        payload = {
            "run_id": self.run_id,
            "engine": self.engine,
            "load": self.load,
            "spec": spec_label(self.spec),
            "offload": self.offload,
            "mlflow_run_id": self.mlflow_run_id,
            "video": video_name(self.manifest.output_video, self.run_id),
            "event": event,
            **fields,
        }
        line = "LTXJSON " + json.dumps(payload, default=str)
        self.manifest.events.append(line)
        logger.info(line)
        print(line, flush=True)

    def start_run(self, prompt: str = "", pipeline: str = "", params: Optional[dict] = None) -> None:
        if prompt:
            self.manifest.prompt = prompt[:200] + "…" if len(prompt) > 200 else prompt
        if pipeline:
            self.engine = pipeline
            self.manifest.pipeline = pipeline
        if params:
            self.spec = params
            self.offload = str(params.get("offload") or self.offload)
            self.manifest.parameters = params
        run_counter.labels(engine=self.engine, offload=self.offload).inc()
        run_active.set(1)
        self._publish_info("")
        self.log("START")
        self._set_gauges()
        self._sampling = True
        self._sampler = threading.Thread(target=self._sample_loop, name="ltx-obs-sample", daemon=True)
        self._sampler.start()

    def start_stage(self, stage_name: str) -> None:
        self.stage_starts[stage_name] = time.time()
        self.current_stage = stage_name
        stage_running.labels(stage=stage_name).set(1)
        self.log("STAGE_START", stage=stage_name)
        self._set_gauges()

    def end_stage(self, stage_name: str, extra_metrics=None) -> None:
        stage_running.labels(stage=stage_name).set(0)
        duration = None
        if stage_name in self.stage_starts:
            duration = time.time() - self.stage_starts[stage_name]
            duration_histogram.labels(stage=stage_name, engine=self.engine, offload=self.offload).observe(duration)
            self.manifest.metrics[f"stage_{stage_name}_s"] = duration
        if extra_metrics:
            self.manifest.metrics.update(extra_metrics)
        if self.current_stage == stage_name:
            self.current_stage = None
        self.log("STAGE_END", stage=stage_name, duration_s=None if duration is None else round(duration, 3))
        self._set_gauges()

    def _set_gauges(self) -> dict[str, Any]:
        sample: dict[str, Any] = {"t": time.time(), "run_id": self.run_id, "stage": self.current_stage}
        try:
            import psutil

            proc = psutil.Process()
            mem = psutil.virtual_memory()
            rss = proc.memory_info().rss
            memory_gauge.labels(type="rss").set(rss)
            memory_gauge.labels(type="unified").set(mem.used)
            cpu = proc.cpu_percent(interval=None)
            cpu_gauge.set(cpu)
            sample["rss"] = rss
            sample["unified"] = mem.used
            sample["cpu_percent"] = cpu
        except Exception:
            pass
        try:
            import torch

            if torch.backends.mps.is_available():
                allocated = torch.mps.current_allocated_memory()
                driver = torch.mps.driver_allocated_memory()
                memory_gauge.labels(type="mps_allocated").set(allocated)
                memory_gauge.labels(type="mps_driver").set(driver)
                sample["mps_allocated"] = allocated
                sample["mps_driver"] = driver
        except Exception:
            gpu_util_gauge.set(0)
        try:
            with self._sample_lock:
                with self.samples_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(sample) + "\n")
        except OSError:
            pass
        return sample

    def _sample_loop(self) -> None:
        while self._sampling:
            self._set_gauges()
            time.sleep(5)

    def end_run(self, output_video: str, success: bool = True, extra_metrics=None) -> None:
        self._sampling = False
        status = "succeeded" if success else "failed"
        self.manifest.output_video = output_video
        self.manifest.status = status
        self.manifest.metrics["total_duration"] = time.time() - self.start_time
        if extra_metrics:
            self.manifest.metrics.update(extra_metrics)
        try:
            path = Path(output_video)
            if path.exists():
                video_bytes_gauge.set(path.stat().st_size)
        except OSError:
            pass
        run_active.set(0)
        run_finished.labels(engine=self.engine, offload=self.offload, status=status).inc()
        self._publish_info(output_video)
        self._set_gauges()
        dest = Path("observability/runs") / self.run_id
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "manifest.json").write_text(json.dumps(asdict(self.manifest), indent=2))
        self.log(
            "END",
            status=status,
            duration_s=round(self.manifest.metrics["total_duration"], 3),
            video=video_name(output_video, self.run_id),
        )
