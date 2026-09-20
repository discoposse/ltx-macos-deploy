from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from shutil import which
from typing import Any, Optional
from urllib.parse import quote

from lab import ledger, omlx, occupancy
from lab.hostinfo import LOAD_NAME, capture_host
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
    OccupancyView,
    Readiness,
    ReadinessState,
    Run,
    RunState,
    RunTrace,
)


ACTIONS = (
    LabAction("obs_up", "Start observability stack", "observability", False),
    LabAction("obs_down", "Stop observability stack", "observability", True, "Stops only ltx-obs containers."),
    LabAction("lab_down", "Stop LTX lab", "lab", True, "Stops LTX API, console, MLflow, and ltx-obs. Leaves oMLX running."),
    LabAction("cancel_run", "Cancel running generation", "lab", True, "Stops the LTX worker process."),
    LabAction(
        "omlx_clear_cache",
        "Clear oMLX hot + SSD cache",
        "omlx",
        True,
        "Drops oMLX prefix cache. The next rewrite is a cold prefill; video generation is unchanged.",
    ),
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
            omlx=f"{omlx.base_url()}/admin",
        )

    def engines(self):
        return occupancy.detect_engines()

    def readiness(self) -> Readiness:
        try:
            engines = self.engines()
        except Exception:
            engines = occupancy.detect_engines()
        distilled = next((e for e in engines if e.id == EngineId.ltx_distilled), None)
        docker_ok = which("docker") is not None
        grafana_ok, grafana_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['grafana']}/api/health")
        prom_ok, prom_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['prometheus']}/-/ready")
        loki_ok, loki_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['loki']}/ready")
        mlflow_ok, mlflow_d = occupancy.http_ok(f"http://127.0.0.1:{self.ports['mlflow']}")
        omlx_info = omlx.status()
        omlx_ready = bool(omlx_info.get("ready"))
        omlx_detail = omlx_info.get("error") or (
            f"{omlx_info.get('default_model') or 'no model'} · {omlx_info.get('url')} · SSD cache {omlx_info.get('cache', {}).get('ssd_dir')}"
        )
        api_ok = occupancy.port_open(self.ports["lab_api"])
        console_ok = occupancy.port_open(self.ports["console"]) or occupancy.port_open(self.ports["lab_api"])
        venv = LTX_ROOT / ".venv/bin/python"
        weights_up = bool(distilled and distilled.ready)
        weights_detail = (distilled.blocked_reason if distilled else "engine list missing") or "Split 2.5 pack present"
        components = [
            Component("docker", "Docker Desktop", "host", "up" if docker_ok else "down", True, "Required for ltx-obs", "Open Docker Desktop"),
            Component("weights", "LTX-2 distilled weights", "weights", "up" if weights_up else "down", True, weights_detail, "Run ./setup-ltx-macos.sh"),
            Component("venv", "LTX Python environment", "engine", "up" if venv.exists() else "down", True, str(venv), "cd LTX-2 && uv sync"),
            Component("lab-api", "Lab control plane", "control", "up" if api_ok else "down", True, f"127.0.0.1:{self.ports['lab_api']}", "Run ./labctl up"),
            Component("console", "Carbon console", "control", "up" if console_ok else "down", True, self.links().console, "Run ./labctl up"),
            Component("grafana", "Grafana (ltx-obs)", "observe", "up" if grafana_ok else "down", True, grafana_d, "Run ./labctl up"),
            Component("prometheus", "Prometheus (ltx-obs)", "observe", "up" if prom_ok else "down", True, prom_d, "Run ./labctl up"),
            Component("loki", "Loki (ltx-obs)", "observe", "up" if loki_ok else "down", False, loki_d, "Run ./labctl up"),
            Component("mlflow", "MLflow UI", "observe", "up" if mlflow_ok else "down", False, mlflow_d, "uv pip install mlflow in LTX-2 venv"),
            Component(
                "omlx",
                "oMLX prompt rewrite",
                "text",
                "up" if omlx_ready else "down",
                False,
                omlx_detail,
                "Open oMLX.app or run: omlx start",
            ),
        ]
        required_down = [c for c in components if c.required and c.state != "up"]
        state = ReadinessState.ready if not required_down else ReadinessState.blocked
        if not api_ok:
            state = ReadinessState.starting if not required_down else ReadinessState.blocked
        try:
            occ = occupancy.occupancy_view(exclusive=self._lease is not None)
        except Exception:
            occ = OccupancyView(band="ltx-81xx", attached_neighbors=(), exclusive=False)
        return Readiness(
            state=state,
            checked_at=time.time(),
            components=components,
            occupancy=occ,
            links=self.links(),
            engines=engines,
        )

    def metrics_text(self) -> str:
        def esc(value) -> str:
            return str(value or "none").replace("\\", "\\\\").replace("\"", "\\\"")

        lines = [
            "# HELP ltx_ledger_runs Generations stored in the lab ledger by state",
            "# TYPE ltx_ledger_runs gauge",
        ]
        counts: dict[str, int] = {}
        runs = self.list_runs(80)
        for run in runs:
            counts[run.state.value] = counts.get(run.state.value, 0) + 1
        if not counts:
            lines.append('ltx_ledger_runs{state="none"} 0')
        for state, n in sorted(counts.items()):
            lines.append(f'ltx_ledger_runs{{state="{esc(state)}"}} {n}')
        latest = runs[0] if runs else None
        lines += [
            "# HELP ltx_run_info Identity of the most recent ledger run",
            "# TYPE ltx_run_info gauge",
        ]
        if latest:
            spec = latest.request.spec
            artifact = (latest.artifact.path if latest.artifact else f"runs/{latest.id}/output.mp4")
            labels = ",".join(
                [
                    f'run_id="{esc(latest.id)}"',
                    f'engine="{esc(latest.request.engine.value)}"',
                    f'load="{LOAD_NAME}"',
                    f'spec="{esc(f"{spec.height}x{spec.width}x{spec.frames}")}"',
                    f'offload="{esc(spec.offload)}"',
                    f'video="{esc(Path(artifact).name)}"',
                    f'mlflow_run_id="{esc(latest.trace.mlflow_run_id)}"',
                    f'state="{esc(latest.state.value)}"',
                ]
            )
            lines.append(f"ltx_run_info{{{labels}}} 1")
            if latest.finished_at and latest.started_at:
                lines += [
                    "# HELP ltx_last_run_duration_seconds Wall time of the most recent finished run",
                    "# TYPE ltx_last_run_duration_seconds gauge",
                    f"ltx_last_run_duration_seconds {latest.finished_at - latest.started_at}",
                ]
        else:
            lines.append('ltx_run_info{run_id="none",engine="none",load="none",spec="none",offload="none",video="none",mlflow_run_id="none",state="none"} 0')
        lines.append("")
        return "\n".join(lines)

    def generate(self, request: GenerationRequest, omlx_evidence: Optional[dict[str, Any]] = None) -> Run:
        profile = next((e for e in self.engines() if e.id is request.engine), None)
        if profile is None:
            raise EngineBlocked(f"Unknown engine {request.engine.value}")
        if not profile.ready:
            raise EngineBlocked(profile.blocked_reason or f"{profile.label} is not ready")
        if profile.modality.value != "video":
            raise EngineBlocked(
                f"{profile.label} rewrites prompts only. Generate video with LTX-2 Distilled, or use Rewrite with oMLX first."
            )
        busy = ledger.active_run()
        if busy:
            busy = self.get(busy.id) or busy
            if not busy.is_terminal():
                raise LabBusy(f"Run {busy.id} is {busy.state.value}")
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        dest = ledger.run_dir(run_id)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            (dest / "host.json").write_text(
                json.dumps(capture_host(request.engine.value, request.spec.to_dict()), indent=2)
            )
        except Exception:
            pass
        self._write_omlx_evidence(dest, request, omlx_evidence)
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

    def _write_omlx_evidence(
        self,
        dest: Path,
        request: GenerationRequest,
        evidence: Optional[dict[str, Any]],
    ) -> None:
        payload: dict[str, Any] = {}
        if isinstance(evidence, dict):
            payload.update(
                {
                    key: value
                    for key, value in evidence.items()
                    if key not in {"snapshot"}
                }
            )
        payload["prompt"] = request.prompt
        try:
            payload["snapshot"] = omlx.snapshot(
                model=payload.get("model"),
                prompt=str(payload.get("source_prompt") or request.prompt),
                do_probe=True,
            )
            snap = payload["snapshot"] or {}
            payload.setdefault("model", snap.get("model"))
            payload.setdefault("cache", snap.get("cache"))
            if snap.get("probe") and not payload.get("probe"):
                payload["probe"] = snap.get("probe")
        except Exception as exc:
            payload["snapshot_error"] = str(exc)
        try:
            (dest / "omlx.json").write_text(json.dumps(omlx.drop_secrets(payload), indent=2))
        except Exception:
            pass

    def get(self, run_id: str) -> Optional[Run]:
        run = ledger.load_run(run_id)
        if not run:
            return None
        return self._hydrate(run, persist=True)

    def list_runs(self, limit: int = 40) -> list[Run]:
        return [self._hydrate(r, persist=False) for r in ledger.list_runs(limit)]

    def _hydrate(self, run: Run, persist: bool) -> Run:
        before = run.state
        run = ledger.merge_worker_status(run)
        if run.pid and run.state in {RunState.queued, RunState.running}:
            if not _pid_alive(run.pid):
                video = ledger.run_dir(run.id) / "output.mp4"
                if video.exists() and video.stat().st_size > 0:
                    run.state = RunState.succeeded
                    run.finished_at = run.finished_at or time.time()
                else:
                    run.state = RunState.failed
                    run.finished_at = run.finished_at or time.time()
                    run.error = run.error or "Worker exited without writing output.mp4"
        if persist or run.state is not before:
            ledger.save_run(run)
        return run

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
        dest = ledger.run_dir(run_id)
        log_path = dest / "worker.log"
        log = log_path.read_text(errors="replace")[-12000:] if log_path.exists() else ""
        host = _read_json(dest / "host.json") or {}
        samples = _read_jsonl(dest / "samples.jsonl")
        omlx_pack = _read_json(dest / "omlx.json") or {}
        cache = _omlx_report(omlx_pack)
        grafana = self.links().grafana
        mlflow = self.links().mlflow
        spec = run.request.spec
        load = str(host.get("load") or LOAD_NAME)
        video = f"{run.id}/output.mp4"
        from_ms, to_ms = _grafana_window(run)
        grafana_run = (
            f"{grafana}/d/ltx-run-trace?orgId=1&var-run_id={quote(run.id)}"
            f"&from={from_ms}&to={to_ms}&theme=dark"
        )
        solo = (
            f"{grafana}/d-solo/ltx-run-trace/run-trace?orgId=1&theme=dark"
            f"&from={from_ms}&to={to_ms}&var-run_id={quote(run.id)}"
        )
        mlflow_run = mlflow
        if run.trace.mlflow_run_id and run.trace.mlflow_experiment_id:
            mlflow_run = f"{mlflow}/#/experiments/{run.trace.mlflow_experiment_id}/runs/{run.trace.mlflow_run_id}"
        elif run.trace.mlflow_run_id:
            mlflow_run = f"{mlflow}/#/search?searchFilter=tags.run_id%3D{run.id}"
        grafana_ok, _ = occupancy.http_ok(f"{grafana}/api/health")
        duration = None
        if run.started_at and run.finished_at:
            duration = round(run.finished_at - run.started_at, 2)
        stages = [s.to_dict() for s in run.trace.stages]
        return {
            "run": run.to_dict(),
            "log": log,
            "identity": {
                "run_id": run.id,
                "load": load,
                "video": video,
                "engine": run.request.engine.value,
                "spec": f"{spec.height}x{spec.width}x{spec.frames}",
                "offload": spec.offload,
                "mlflow_run_id": run.trace.mlflow_run_id,
            },
            "job": {
                "run_id": run.id,
                "state": run.state.value,
                "engine": run.request.engine.value,
                "load": load,
                "prompt": run.request.prompt,
                "height": spec.height,
                "width": spec.width,
                "frames": spec.frames,
                "fps": spec.fps,
                "seed": spec.seed,
                "offload": spec.offload,
                "started_at": run.started_at or run.created_at,
                "finished_at": run.finished_at,
                "duration_s": duration,
                "video": video,
                "size_bytes": None if run.artifact is None else run.artifact.size_bytes,
                "sha256": None if run.artifact is None else run.artifact.sha256,
                "mlflow_run_id": run.trace.mlflow_run_id,
                "mlflow_experiment_id": run.trace.mlflow_experiment_id,
                "error": run.error,
                "pinned": run.pinned,
            },
            "hardware": {
                "hostname": host.get("hostname"),
                "hw_model": host.get("hw_model"),
                "processor": host.get("processor"),
                "arch": host.get("arch"),
                "cpu_count": host.get("cpu_count"),
                "memory_bytes": host.get("memory_bytes"),
                "memory_available_bytes": host.get("memory_available_bytes"),
                "mps": host.get("mps"),
                "mps_recommended": host.get("mps_recommended"),
                "mps_allocated": host.get("mps_allocated"),
                "mps_driver": host.get("mps_driver"),
            },
            "software": {
                "os": host.get("os"),
                "python": host.get("python"),
                "python_impl": host.get("python_impl"),
                "torch": host.get("torch"),
                "engine": host.get("engine") or run.request.engine.value,
                "load": load,
                "offload": spec.offload,
                "ltx_tree": host.get("ltx_tree"),
            },
            "host": host or None,
            "omlx": omlx_pack or None,
            "cache": cache,
            "samples": samples,
            "charts": {
                "stages": stages,
                "memory": [
                    {"t": row.get("t"), "rss": row.get("rss"), "unified": row.get("unified"), "mps_allocated": row.get("mps_allocated")}
                    for row in samples
                    if row.get("t") is not None
                ],
                "cpu": [{"t": row.get("t"), "v": row.get("cpu_percent")} for row in samples if row.get("cpu_percent") is not None],
            },
            "grafana_up": grafana_ok,
            "window": {"from_ms": from_ms, "to_ms": to_ms},
            "embeds": [
                {"id": "memory", "title": "Memory", "panel_id": 2, "url": f"{solo}&panelId=2"},
                {"id": "cpu", "title": "CPU", "panel_id": 3, "url": f"{solo}&panelId=3"},
                {"id": "mps", "title": "MPS", "panel_id": 4, "url": f"{solo}&panelId=4"},
                {"id": "stages", "title": "Stage duration", "panel_id": 5, "url": f"{solo}&panelId=5"},
                {"id": "logs", "title": "Worker log", "panel_id": 6, "url": f"{solo}&panelId=6"},
            ],
            "layers": [
                {"id": "prompt", "title": "Prompt", "why": "User intent", "note": run.request.prompt},
                {"id": "encode", "title": "Text encoder", "why": "Gemma embeddings", "note": "Stage encode"},
                {"id": "denoise", "title": "Transformer", "why": "Distilled denoise at half then full res", "note": "Stage generate"},
                {"id": "decode", "title": "VAE + mux", "why": "Pixels + audio to mp4", "note": "Stage write"},
            ],
            "links": {
                **self.links().to_dict(),
                "grafana_run": grafana_run,
                "grafana_overview": f"{grafana}/d/ltx-overview",
                "grafana_queries": f"{grafana}/d/ltx-queries",
                "mlflow_run": mlflow_run,
                "prometheus_run": (
                    f"{self.links().prometheus}/graph?g0.expr="
                    + quote(f'ltx_run_info{{run_id="{run.id}"}}')
                    + f"&g0.from={from_ms}&g0.to={to_ms}"
                ),
            },
        }

    def omlx_status(self) -> dict:
        return omlx.status()

    def omlx_snapshot(self, prompt: Optional[str] = None, model: Optional[str] = None) -> dict:
        return omlx.snapshot(model=model, prompt=prompt, do_probe=bool(prompt))

    def rewrite_prompt(self, prompt: str, model: Optional[str] = None) -> dict:
        return omlx.rewrite(prompt, model=model)

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
        elif action_id == "omlx_clear_cache":
            cleared = omlx.clear_cache()
            code, log = 0, json.dumps(cleared, indent=2)
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
    try:
        subprocess.run(
            [
                str(LTX_ROOT / ".venv/bin/python"),
                "-c",
                (
                    "import mlflow; from mlflow.tracking import MlflowClient; "
                    f"mlflow.set_tracking_uri('sqlite:///{db}'); "
                    "mlflow.set_experiment('ltx-lab'); "
                    "c=MlflowClient(); e=c.get_experiment_by_name('ltx-lab'); "
                    "c.set_experiment_tag(e.experiment_id,'purpose','LTX-2 distilled video generations'); "
                    "c.set_experiment_tag(e.experiment_id,'grafana','http://127.0.0.1:3300/d/ltx-overview'); "
                    "c.set_experiment_tag(e.experiment_id,'grafana_trace','http://127.0.0.1:3300/d/ltx-run-trace'); "
                    "c.set_experiment_tag(e.experiment_id,'console','http://127.0.0.1:8188'); "
                    "print(e.experiment_id)"
                ),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        pass


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


def _omlx_report(pack: dict[str, Any]) -> dict[str, Any]:
    snap = pack.get("snapshot") if isinstance(pack, dict) else {}
    if not isinstance(snap, dict):
        snap = {}
    cache = dict(pack.get("cache") or snap.get("cache") or {})
    probe = pack.get("probe") or snap.get("probe") or {}
    runtime = snap.get("runtime") or {}
    model_runtime = runtime.get("model") or {}
    usage = pack.get("usage") or {}
    return {
        "used": bool(pack),
        "model": pack.get("model") or snap.get("model"),
        "default_model": snap.get("default_model"),
        "source_prompt": pack.get("source_prompt"),
        "rewritten": pack.get("prompt") if pack.get("source_prompt") else None,
        "url": pack.get("url") or snap.get("url"),
        "admin": snap.get("admin"),
        "models_dir": cache.get("models_dir") or snap.get("models_dir"),
        "settings_path": cache.get("settings_path"),
        "base_path": cache.get("base_path") or runtime.get("base_path"),
        "ssd_dir": cache.get("ssd_dir") or runtime.get("ssd_dir"),
        "ssd_max": cache.get("ssd_max"),
        "response_state_dir": cache.get("response_state_dir") or runtime.get("response_state_dir"),
        "hot_cache_only": cache.get("hot_cache_only"),
        "hot_cache_max_size": cache.get("hot_cache_max_size"),
        "cache_enabled": cache.get("enabled"),
        "block_size": (probe or {}).get("block_size") or model_runtime.get("block_size"),
        "indexed_blocks": model_runtime.get("indexed_blocks"),
        "ssd_files": model_runtime.get("num_files"),
        "ssd_bytes": model_runtime.get("total_size_bytes"),
        "hot_bytes": model_runtime.get("hot_cache_size_bytes"),
        "hot_max_bytes": model_runtime.get("hot_cache_max_bytes"),
        "hits": model_runtime.get("hits"),
        "misses": model_runtime.get("misses"),
        "cached_tokens": usage.get("cached_tokens"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "cache_hit": pack.get("cache_hit"),
        "ttft_ms": usage.get("ttft_ms"),
        "probe": probe or None,
        "runtime": runtime or None,
        "catalog": snap.get("catalog") or [],
    }


def _read_json(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path, limit: int = 360) -> list:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _grafana_window(run: Run) -> tuple[int, int]:
    start = (run.started_at or run.created_at or time.time()) - 30
    end = (run.finished_at or time.time()) + 30
    if end <= start:
        end = start + 60
    return int(start * 1000), int(end * 1000)
