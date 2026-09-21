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


def list_run_ids() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return [child.name for child in sorted(RUNS_DIR.iterdir(), reverse=True) if child.is_dir()]


def list_runs(limit: int = 40) -> list[Run]:
    runs: list[Run] = []
    for run_id in list_run_ids():
        run = load_run(run_id)
        if run:
            runs.append(run)
        if len(runs) >= limit:
            break
    return runs


def running_run() -> Optional[Run]:
    for run in list_runs(200):
        if run.state == RunState.running:
            return run
    return None


def queued_runs() -> list[Run]:
    queued = [run for run in list_runs(200) if run.state == RunState.queued]
    queued.sort(key=lambda run: run.created_at)
    return queued


def next_queued() -> Optional[Run]:
    waiting = queued_runs()
    return waiting[0] if waiting else None


def active_run() -> Optional[Run]:
    return running_run() or next_queued()


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
            pin = json.loads(pin_path.read_text())
            pin["bytes"] = dir_size(child)
            pins.append(pin)
    return pins


def _safe_id(value: str, kind: str = "id") -> str:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError(f"invalid {kind}")
    return text


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def run_bytes(run_id: str) -> int:
    return dir_size(run_dir(run_id))


def storage_snapshot(limit: int = 80) -> dict:
    runs_payload = []
    runs_bytes = 0
    for run_id in list_run_ids():
        size = run_bytes(run_id)
        runs_bytes += size
        run = load_run(run_id)
        if run is None:
            continue
        prompt = run.request.prompt.strip().replace("\n", " ")
        runs_payload.append(
            {
                "id": run.id,
                "state": run.state.value,
                "pinned": run.pinned,
                "bytes": size,
                "created_at": run.created_at,
                "finished_at": run.finished_at,
                "prompt": prompt[:160],
            }
        )
    refs_bytes = dir_size(REFS_DIR) if REFS_DIR.exists() else 0
    return {
        "runs_bytes": runs_bytes,
        "references_bytes": refs_bytes,
        "total_bytes": runs_bytes + refs_bytes,
        "run_count": len(runs_payload),
        "pin_count": len(list_pins()) if REFS_DIR.exists() else 0,
        "runs": runs_payload[:limit],
    }


def delete_run(run_id: str) -> dict:
    run_id = _safe_id(run_id, "run id")
    run = load_run(run_id)
    if run and not run.is_terminal():
        raise ValueError(f"Cannot delete an active run ({run.state.value})")
    dest = run_dir(run_id)
    if not dest.exists():
        raise FileNotFoundError(run_id)
    freed = dir_size(dest)
    shutil.rmtree(dest)
    return {"id": run_id, "bytes": freed, "kind": "run"}


def delete_pin(pin_id: str) -> dict:
    pin_id = _safe_id(pin_id, "pin id")
    dest = REFS_DIR / pin_id
    pin_path = dest / "pin.json"
    if not dest.exists() or not pin_path.exists():
        raise FileNotFoundError(pin_id)
    pin = json.loads(pin_path.read_text())
    run_id = pin.get("run_id")
    freed = dir_size(dest)
    shutil.rmtree(dest)
    if run_id:
        run = load_run(run_id)
        if run and run.pinned:
            run.pinned = False
            save_run(run)
    return {"id": pin_id, "bytes": freed, "kind": "reference", "run_id": run_id}


def reclaim(*, keep: int = 5, keep_pinned: bool = True) -> dict:
    if keep < 0:
        raise ValueError("keep must be >= 0")
    runs = [run for run in (load_run(run_id) for run_id in list_run_ids()) if run]
    runs.sort(key=lambda run: run.created_at, reverse=True)
    kept: list[str] = []
    deleted: list[dict] = []
    skipped: list[dict] = []
    kept_count = 0
    for run in runs:
        if not run.is_terminal():
            skipped.append({"id": run.id, "reason": "active"})
            continue
        if keep_pinned and run.pinned:
            skipped.append({"id": run.id, "reason": "pinned"})
            continue
        if kept_count < keep:
            kept.append(run.id)
            kept_count += 1
            continue
        deleted.append(delete_run(run.id))
    return {
        "keep": keep,
        "keep_pinned": keep_pinned,
        "kept": kept,
        "deleted": deleted,
        "skipped": skipped,
        "freed_bytes": sum(item["bytes"] for item in deleted),
        "deleted_count": len(deleted),
    }
