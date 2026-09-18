from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from shutil import which
from typing import Optional

from lab import ledger, occupancy
from lab.types import (
    LTX_BAND,
    LTX_ROOT,
    PIDS_PATH,
    ROOT,
    RUNS_DIR,
    Component,
    EngineBlocked,
    EngineId,
    GenerationRequest,
    LabAction,
    LabBusy,
    LabLinks,
    OccupancyError,
    Readiness,
    ReadinessState,
    Run,
    RunState,
    RunTrace,
)


ACTIONS = (
    LabAction("obs_up", "Start observability stack", "observability", False),
    LabAction("obs_down", "Stop observability stack", "observability", True, "Stops only ltx-obs containers."),
    LabAction("lab_down", "Stop LTX lab", "lab", True, "Stops LTX API, console, MLflow, and ltx-obs. Leaves other labs running."),
    LabAction("cancel_run", "Cancel running generation", "lab", True, "Stops the LTX worker process."),
)


class Lab:
    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = root or ROOT
        self.ports = dict(LTX_BAND)
        self._lease: Optional[dict] = occupancy.read_lease()

    @classmethod
    def open(cls, root: Optional[Path] = None) -> "Lab":
        return cls(root=root)

    def links(self) -> LabLinks:
        p = self.ports
        return LabLinks(
            console=f"http://127.0.0.1:{p['console']}",
            grafana=f"http://127.0.0.1:{p['grafana']}",
            prometheus=f"http://127.0.0.1:{p['prometheus']}",
            mlflow=f"http://127.0.0.1:{p['mlflow']}",
            metrics=f"http://127.0.0.1:{p['metrics']}/metrics",
            loki=f"http://127.0.0.1:{p['loki']}",
        )

    def engines(self):
        return occupancy.detect_engines()

    def readiness(self) -> Readiness:
        engines = self.engines()
        distilled = next(e for e in engines if e.id is EngineId.ltx_distilled)
        docker_ok = which("docker") is not None
        grafana_ok, grafana_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['grafana']}/api/health")
        prom_ok, prom_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['prometheus']}/-/ready")
        loki_ok, loki_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['loki']}/ready")
        mlflow_ok, mlflow_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['mlflow']}")
        api_ok = occupancy.port_open(self.ports["lab_api"])
        console_ok = occupancy.port_open(self.ports["console"]) or occupancy.port_open(self.ports["lab_api"])
        venv = LTX_ROOT / ".venv/bin/python"
        components = [
            Component("docker", "Docker Desktop", "host", "up" if docker_ok else "down", True, "Required for ltx-obs", "Open Docker Desktop"),
            Component("weights", "LTX-2 distilled weights", "weights", "up" if distilled.ready else "down", True, distilled.blocked_reason or "Split 2.5 pack present", "Run ./setup-ltx-macos.sh"),
            Component("venv", "LTX Python environment", "engine", "up" if venv.exists() else "down", True, str(venv), "cd LTX-2 && uv sync"),
            Component("lab-api", "Lab control plane", "control", "up" if api_ok else "down", True, f"127.0.0.1:{self.ports['lab_api']}", "Run ./lab up"),
            Component("console", "Carbon console", "control", "up" if console_ok else "down", True, self.links().console, "Run ./lab up"),
            Component("grafana", "Grafana (ltx-obs)", "observe", "up" if grafana_ok else "down", True, grafana_d, "Run ./lab up"),
            Component("prometheus", "Prometheus (ltx-obs)", "observe", "up" if prom_ok else "down", True, prom_d, "Run ./lab up"),
            Component("loki", "Loki (ltx-obs)", "observe", "up" if loki_ok else "down", False, loki_d, "Run ./lab up"),
            Component("mlflow", "MLflow UI", "observe", "up" if mlflow_ok else "down", False, mlflow_d, "uv pip install mlflow in LTX-2 venv"),
        ]
        required_down = [c for c in components if c.required and c.state != "up"]
        state = ReadinessState.ready if not required_down else ReadinessState.blocked
        if not api_ok:
            state = ReadinessState.starting if not required_down else ReadinessState.blocked
        return Readiness(
            state=state,
            checked_at=time.time(),
            components=components,
            occupancy=occupancy.occupancy_view(exclusive=self._lease is not None),
            links=self.links(),
            engines=engines,
        )

    def generate(self, request: GenerationRequest) -> Run:
        profile = next((e for e in self.engines() if e.id is request.engine), None)
        if profile is None:
            raise EngineBlocked(f"Unknown engine {request.engine.value}")
        if not profile.ready:
            raise EngineBlocked(profile.blocked_reason or f"{profile.label} is not ready")
        if profile.modality.value != "video":
            raise EngineBlocked(f"{profile.label} is detected for later swap; iteration 1 generates video via LTX-2")
        busy = ledger.active_run()
        if busy:
            raise LabBusy(f"Run {busy.id} is {busy.state.value}")
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        dest = ledger.run_dir(run_id)
        dest.mkdir(parents=True, exist_ok=True)
        run = Run(
            id=run_id,
            request=request,
            state=RunState.queued,
            created_at=time.time(),
            trace=RunTrace(run_id=run_id, stages=ledger.new_stages()),
        )
        (dest / "request.json").write_text(json.dumps({
            "run_id": run_id,
            "prompt": request.prompt,
            "engine": request.engine.value,
            "spec": request.spec.to_dict(),
            "output_path": str(dest / "output.mp4"),
            "mlflow_tracking_uri": f"sqlite:///{self.root / 'mlflow.db'}",
            "metrics_port": self.ports["metrics"],
        }, indent=2))
        python = LTX_ROOT / ".venv/bin/python"
        if not python.exists():
            raise OccupancyError(f"LTX venv missing at {python}")
        log_path = dest / "worker.log"
        log_fh = open(log_path, "w")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.root)
        env["MLFLOW_TRACKING_URI"] = f"sqlite:///{self.root / 'mlflow.db'}"
        env["MLFLOW_ALLOW_FILE_STORE"] = "true"
        env["LTX_ROOT"] = str(LTX_ROOT)
        env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.0"
        env["PYTORCH_MPS_LOW_WATERMARK_RATIO"] = "0.0"
        proc = subprocess.Popen(
            [str(python), "-m", "lab.worker", "--request", str(dest / "request.json")],
            cwd=str(self.root),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        run.pid = proc.pid
        run.state = RunState.running
        run.started_at = time.time()
        ledger.save_run(run)
        (dest / "pid").write_text(str(proc.pid))
        return run

    def get(self, run_id: str) -> Optional[Run]:
        run = ledger.load_run(run_id)
        if not run:
            return None
        run = ledger.merge_worker_status(run)
        if run.pid and run.state in {RunState.queued, RunState.running}:
            if not _pid_alive(run.pid) and run.state is RunState.running:
                video = ledger.run_dir(run.id) / "output.mp4"
                if video.exists() and video.stat().st_size > 0:
                    run.state = RunState.succeeded
                    run.finished_at = time.time()
                else:
                    run.state = RunState.failed
                    run.finished_at = time.time()
                    run.error = run.error or "Worker exited without writing output.mp4"
        ledger.save_run(run)
        return run

    def list_runs(self, limit: int = 40) -> list[Run]:
        return [self.get(r.id) or r for r in ledger.list_runs(limit)]

    def wait(self, run_id: str, timeout_s: Optional[float] = None) -> Run:
        start = time.time()
        while True:
            run = self.get(run_id)
            if run is None:
                raise FileNotFoundError(run_id)
            if run.is_terminal():
                return run
            if timeout_s is not None and time.time() - start > timeout_s:
                return run
            time.sleep(2)

    def cancel(self, run_id: str) -> Run:
        run = self.get(run_id)
        if run is None:
            raise FileNotFoundError(run_id)
        if run.is_terminal():
            return run
        if run.pid:
            _terminate_group(run.pid)
        run.state = RunState.cancelled
        run.finished_at = time.time()
        ledger.save_run(run)
        return run

    def pin(self, run_id: str, label: str):
        run = self.get(run_id)
        if run is None:
            raise FileNotFoundError(run_id)
        return ledger.pin_run(run, label)

    def observe(self, run_id: str) -> dict:
        run = self.get(run_id)
        if run is None:
            raise FileNotFoundError(run_id)
        log_path = ledger.run_dir(run_id) / "worker.log"
        log = log_path.read_text(errors="replace")[-8000:] if log_path.exists() else ""
        return {
            "run": run.to_dict(),
            "log": log,
            "layers": [
                {"id": "prompt", "title": "Prompt", "why": "User intent", "note": run.request.prompt},
                {"id": "encode", "title": "Text encoder", "why": "Gemma embeddings", "note": "Stage encode"},
                {"id": "denoise", "title": "Transformer", "why": "Distilled denoise at half then full res", "note": "Stage generate"},
                {"id": "decode", "title": "VAE + mux", "why": "Pixels + audio to mp4", "note": "Stage write"},
            ],
            "links": self.links().to_dict(),
        }

    def actions(self) -> tuple[LabAction, ...]:
        return ACTIONS

    def start_action(self, action_id: str, confirm: bool = False) -> dict:
        action = next((a for a in ACTIONS if a.id == action_id), None)
        if action is None:
            raise KeyError(action_id)
        if action.confirm and not confirm:
            raise PermissionError(action.warning or "confirm required")
        if action_id == "obs_up":
            code, log = start_observability(self.ports)
        elif action_id == "obs_down":
            code, log = stop_observability()
        elif action_id == "lab_down":
            self.down()
            code, log = 0, "lab down requested"
        elif action_id == "cancel_run":
            busy = ledger.active_run()
            if busy:
                self.cancel(busy.id)
                code, log = 0, f"cancelled {busy.id}"
            else:
                code, log = 0, "no active run"
        else:
            raise KeyError(action_id)
        return {"id": action_id, "exit_code": code, "log": log}

    def up(self) -> Readiness:
        occupancy.assert_band_free_or_self(self._lease)
        (self.root / ".lab").mkdir(parents=True, exist_ok=True)
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        start_observability(self.ports)
        start_mlflow(self.ports["mlflow"], self.root)
        self._lease = occupancy.write_lease(self.ports, os.getpid())
        return self.readiness()

    def down(self) -> None:
        busy = ledger.active_run()
        if busy and busy.pid:
            _terminate_group(busy.pid)
        stop_mlflow()
        stop_observability()
        pids = _read_pids()
        for name in ("api", "console", "mlflow"):
            pid = pids.get(name)
            if pid:
                _terminate_group(int(pid))
        if PIDS_PATH.exists():
            PIDS_PATH.unlink()
        lease = self.root / ".lab" / "lease.json"
        if lease.exists():
            lease.unlink()
        self._lease = None


def start_observability(ports: dict[str, int]) -> tuple[int, str]:
    _cleanup_stale_ltx_containers()
    env = os.environ.copy()
    env.update({
        "GRAFANA_PORT": str(ports["grafana"]),
        "PROMETHEUS_PORT": str(ports["prometheus"]),
        "LOKI_PORT": str(ports["loki"]),
        "OTEL_GRPC_PORT": str(ports["otel_grpc"]),
        "OTEL_HTTP_PORT": str(ports["otel_http"]),
        "METRICS_PORT": str(ports["metrics"]),
    })
    proc = subprocess.run(
        ["docker", "compose", "-p", "ltx-obs", "up", "-d", "--remove-orphans"],
        cwd=str(ROOT / "observability"),
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def stop_observability() -> tuple[int, str]:
    proc = subprocess.run(
        ["docker", "compose", "-p", "ltx-obs", "down", "--remove-orphans"],
        cwd=str(ROOT / "observability"),
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _cleanup_stale_ltx_containers() -> None:
    """Remove leftover Created containers from the old project name/ports. Never touch infinia-*."""
    names = occupancy.docker_names()
    stale = [n for n in names if n.startswith("ltx-")]
    if not stale:
        return
    subprocess.run(["docker", "rm", "-f", *stale], capture_output=True, text=True)
    subprocess.run(
        ["docker", "compose", "-p", "observability", "down", "--remove-orphans"],
        cwd=str(ROOT / "observability"),
        capture_output=True,
        text=True,
    )


def start_mlflow(port: int, root: Path) -> None:
    binary = LTX_ROOT / ".venv/bin/mlflow"
    if not binary.exists():
        return
    if occupancy.port_open(port):
        return
    log = open(root / ".lab" / "mlflow.log", "w")
    db = root / "mlflow.db"
    env = os.environ.copy()
    env["MLFLOW_ALLOW_FILE_STORE"] = "true"
    proc = subprocess.Popen(
        [
            str(binary), "ui",
            "--port", str(port),
            "--host", "127.0.0.1",
            "--backend-store-uri", f"sqlite:///{db}",
            "--allowed-hosts", "*",
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    _write_pid("mlflow", proc.pid)


def stop_mlflow() -> None:
    pids = _read_pids()
    pid = pids.get("mlflow")
    if pid:
        _terminate_group(int(pid))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    time.sleep(0.4)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


def _read_pids() -> dict:
    if not PIDS_PATH.exists():
        return {}
    try:
        return json.loads(PIDS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _write_pid(name: str, pid: int) -> None:
    data = _read_pids()
    data[name] = pid
    PIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIDS_PATH.write_text(json.dumps(data, indent=2))
