from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from lab.types import (
    REFS_DIR,
    RUNS_DIR,
    Artifact,
    GenerationRequest,
    ReferencePin,
    Run,
    RunState,
    RunTrace,
    Stage,
)


STAGE_DEFS = (
    ("load", "Load weights"),
    ("encode", "Encode prompt"),
    ("generate", "Denoise + decode"),
    ("write", "Write mp4"),
)


def run_dir(run_id: str) -> Path:
    return RUNS_DIR / run_id


def new_stages() -> list[Stage]:
    return [Stage(name=n, label=l) for n, l in STAGE_DEFS]


_LEDGER_LOCK = threading.Lock()


def save_run(run: Run) -> None:
    path = run_dir(run.id)
    path.mkdir(parents=True, exist_ok=True)
    dest = path / "run.json"
    tmp = path / f".run.json.{os.getpid()}.{threading.get_ident()}.tmp"
    payload = json.dumps(run.to_dict(), indent=2)
    with _LEDGER_LOCK:
        tmp.write_text(payload)
        tmp.replace(dest)


def load_run(run_id: str) -> Optional[Run]:
    path = run_dir(run_id) / "run.json"
    with _LEDGER_LOCK:
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            raw = path.read_text()
        except OSError:
            return None
    try:
        return run_from_dict(json.loads(raw))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def list_runs(limit: int = 40) -> list[Run]:
    if not RUNS_DIR.exists():
        return []
    runs: list[Run] = []
    for child in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        run = load_run(child.name)
        if run:
            runs.append(run)
        if len(runs) >= limit:
            break
    return runs


def active_run() -> Optional[Run]:
    for run in list_runs(80):
        if run.state in {RunState.queued, RunState.running}:
            return run
    return None


def run_from_dict(data: dict) -> Run:
    request = GenerationRequest.from_dict(data["request"])
    trace_data = data.get("trace") or {}
    stages = [
        Stage(
            name=s["name"],
            label=s["label"],
            started_at=s.get("started_at"),
            ended_at=s.get("ended_at"),
            status=s.get("status", "pending"),
        )
        for s in trace_data.get("stages") or []
    ]
    if not stages:
        stages = new_stages()
    artifact = None
    if data.get("artifact"):
        artifact = Artifact(**data["artifact"])
    return Run(
        id=data["id"],
        request=request,
        state=RunState(data["state"]),
        created_at=float(data["created_at"]),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        trace=RunTrace(
            run_id=data["id"],
            mlflow_run_id=trace_data.get("mlflow_run_id"),
            mlflow_experiment_id=trace_data.get("mlflow_experiment_id"),
            stages=stages,
            current_index=int(trace_data.get("current_index") or 0),
            events=list(trace_data.get("events") or []),
        ),
        artifact=artifact,
        error=data.get("error"),
        pid=data.get("pid"),
        pinned=bool(data.get("pinned")),
    )


def merge_worker_status(run: Run) -> Run:
    """Overlay worker-written status.json onto the ledger row."""
    status_path = run_dir(run.id) / "status.json"
    if not status_path.exists():
        return run
    try:
        status = json.loads(status_path.read_text())
    except json.JSONDecodeError:
        return run
    if status.get("state"):
        run.state = RunState(status["state"])
    if status.get("started_at"):
        run.started_at = status["started_at"]
    if status.get("finished_at"):
        run.finished_at = status["finished_at"]
    if status.get("error"):
        run.error = status["error"]
    if status.get("mlflow_run_id"):
        run.trace.mlflow_run_id = status["mlflow_run_id"]
    if status.get("mlflow_experiment_id"):
        run.trace.mlflow_experiment_id = str(status["mlflow_experiment_id"])
    if status.get("stages"):
        run.trace.stages = [
            Stage(
                name=s["name"],
                label=s["label"],
                started_at=s.get("started_at"),
                ended_at=s.get("ended_at"),
                status=s.get("status", "pending"),
            )
            for s in status["stages"]
        ]
        running = next((i for i, s in enumerate(run.trace.stages) if s.status == "running"), None)
        run.trace.current_index = running if running is not None else max(
            (i for i, s in enumerate(run.trace.stages) if s.status == "succeeded"),
            default=0,
        )
    if status.get("events"):
        run.trace.events = list(status["events"])[-400:]
    artifact_path = run_dir(run.id) / "output.mp4"
    if artifact_path.exists() and artifact_path.stat().st_size > 0:
        run.artifact = Artifact(
            kind="video/mp4",
            path=str(artifact_path),
            size_bytes=artifact_path.stat().st_size,
            sha256=status.get("sha256") or "",
        )
    return run


def pin_run(run: Run, label: str) -> ReferencePin:
    if run.state != RunState.succeeded or run.artifact is None:
        raise ValueError("Only a succeeded run with an mp4 can be pinned")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label).strip("-") or "reference"
    dest = REFS_DIR / f"{run.id}-{safe}"
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(run.artifact.path)
    copied = dest / "output.mp4"
    if src.exists():
        shutil.copy2(src, copied)
    shutil.copy2(run_dir(run.id) / "run.json", dest / "run.json")
    pin = ReferencePin(
        id=dest.name,
        run_id=run.id,
        label=label,
        pinned_at=time.time(),
        request=run.request,
        artifact=Artifact(
            kind="video/mp4",
            path=str(copied),
            size_bytes=copied.stat().st_size if copied.exists() else 0,
            sha256=run.artifact.sha256,
        ),
        trace=run.trace,
    )
    (dest / "pin.json").write_text(json.dumps(pin.to_dict(), indent=2))
    run.pinned = True
    save_run(run)
    return pin


def list_pins() -> list[dict]:
    if not REFS_DIR.exists():
        return []
    pins = []
    for child in sorted(REFS_DIR.iterdir(), reverse=True):
        pin_path = child / "pin.json"
        if pin_path.exists():
            pins.append(json.loads(pin_path.read_text()))
    return pins
