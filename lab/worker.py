"""LTX distilled/DFR worker. Runs inside LTX-2/.venv. Writes runs/{id}/status.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STAGES = (
    ("load", "Load weights"),
    ("encode", "Encode prompt"),
    ("generate", "Denoise + decode"),
    ("write", "Write mp4"),
)


def _mlflow_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    return text[:500]


def _mlflow_log_params(params: dict) -> None:
    if not params:
        return
    import mlflow

    items = [(str(k), _mlflow_value(v)) for k, v in params.items() if v is not None and v != ""]
    for index in range(0, len(items), 100):
        mlflow.log_params(dict(items[index : index + 100]))


def _mlflow_log_artifacts(dest: Path, output_path: Path) -> None:
    import mlflow

    if output_path.exists():
        mlflow.log_artifact(str(output_path), artifact_path="video")
    for name, folder in (
        ("worker.log", "logs"),
        ("host.json", "report"),
        ("samples.jsonl", "report"),
        ("comfy.json", "comfy"),
        ("comfy.workflow.json", "comfy"),
        ("comfy.params.json", "comfy"),
        ("comfy.trace.json", "comfy"),
        ("request.json", "report"),
        ("run.json", "report"),
    ):
        path = dest / name
        if path.exists() and path.stat().st_size > 0:
            mlflow.log_artifact(str(path), artifact_path=folder)


def _run_comfy(payload, dest, start_stage, end_stage, log, flush, started, observer) -> int:
    from lab.comfy import run_job
    from lab.hostinfo import capture_host
    from lab.types import VideoSpec

    spec = payload.get("spec") or {}
    output_path = Path(payload["output_path"])
    current = {"name": "load"}

    def on_stage(name: str) -> None:
        if current["name"] != name:
            end_stage(current["name"])
            current["name"] = name
            start_stage(name)

    start_stage("load")
    try:
        host = capture_host(payload.get("engine") or "comfyui", spec, f"comfyui-{payload.get('workflow') or 'default'}")
        (dest / "host.json").write_text(json.dumps(host, indent=2))
    except Exception as exc:
        log(f"host snapshot skipped: {exc}")
    log(f"ComfyUI workflow={payload.get('workflow') or 'default'}")
    pack = run_job(
        prompt=payload["prompt"],
        spec=VideoSpec.from_dict(spec),
        dest=dest,
        workflow=payload.get("workflow"),
        run_id=payload["run_id"],
        log=log,
        on_stage=on_stage,
    )
    end_stage(current["name"])
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    duration = time.time() - started
    log(f"END run_id={payload['run_id']} video={output_path} bytes={output_path.stat().st_size} duration={duration:.1f}s comfy={pack.get('prompt_id')}")
    extra_metrics = {"total_duration": duration, "size_bytes": output_path.stat().st_size}
    trace = pack.get("trace") if isinstance(pack.get("trace"), dict) else {}
    if trace.get("duration_s") is not None:
        extra_metrics["comfy_exec_s"] = trace["duration_s"]
    if observer:
        try:
            observer.end_run(str(output_path), success=True, extra_metrics=extra_metrics)
        except Exception:
            pass
    try:
        import mlflow
        if mlflow.active_run():
            graph_params = pack.get("params") if isinstance(pack.get("params"), dict) else {}
            _mlflow_log_params(
                {
                    "workflow": pack.get("workflow") or "",
                    "comfy_prompt_id": pack.get("prompt_id") or "",
                    "comfy_version": pack.get("comfy_version") or "",
                    **graph_params,
                }
            )
            mlflow.log_metric("duration_s", duration)
            mlflow.log_metric("size_bytes", output_path.stat().st_size)
            if trace.get("duration_s") is not None:
                mlflow.log_metric("comfy_exec_s", float(trace["duration_s"]))
            if trace.get("node_count") is not None:
                mlflow.log_metric("comfy_nodes", float(trace["node_count"]))
            for node in (trace.get("nodes") or [])[:20]:
                node_id = str(node.get("node") or "node")
                if node.get("duration_s") is None:
                    continue
                mlflow.log_metric(f"comfy_node_{node_id}_s", float(node["duration_s"]))
            try:
                import torch

                if torch.backends.mps.is_available():
                    mlflow.log_metric("mps_allocated", float(torch.mps.current_allocated_memory()))
                    mlflow.log_metric("mps_driver", float(torch.mps.driver_allocated_memory()))
            except Exception:
                pass
            host_path = dest / "host.json"
            if host_path.exists():
                try:
                    mlflow.log_dict(json.loads(host_path.read_text()), "host.json")
                except Exception:
                    pass
            _mlflow_log_artifacts(dest, output_path)
            mlflow.set_tag("status", "succeeded")
            mlflow.set_tag("workflow", pack.get("workflow") or "")
            mlflow.end_run()
    except Exception:
        pass
    flush(
        state="succeeded",
        finished_at=time.time(),
        sha256=digest,
        metrics={
            "duration_s": duration,
            "size_bytes": output_path.stat().st_size,
            "comfy_prompt_id": pack.get("prompt_id"),
            "comfy_exec_s": trace.get("duration_s"),
            "comfy_nodes": trace.get("node_count"),
        },
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request_path = Path(args.request)
    payload = json.loads(request_path.read_text())
    run_id = payload["run_id"]
    dest = request_path.parent
    status_path = dest / "status.json"

    stages = [{"name": n, "label": l, "started_at": None, "ended_at": None, "status": "pending"} for n, l in STAGES]
    events: list[str] = []
    started = time.time()

    engine = payload.get("engine") or "ltx-distilled"
    spec = payload.get("spec") or {}
    load_name = {
        "ltx-dfr": "ltx-2.5-22b-dfr",
        "comfyui": f"comfyui-{payload.get('workflow') or 'default'}",
    }.get(engine, "ltx-2.5-22b-distilled")
    mlflow_run_id = None
    mlflow_experiment_id = None
    observer = None

    def flush(**extra):
        body = {
            "run_id": run_id,
            "state": extra.get("state", "running"),
            "started_at": started,
            "finished_at": extra.get("finished_at"),
            "error": extra.get("error"),
            "mlflow_run_id": extra.get("mlflow_run_id", mlflow_run_id),
            "mlflow_experiment_id": extra.get("mlflow_experiment_id", mlflow_experiment_id),
            "sha256": extra.get("sha256"),
            "stages": stages,
            "events": events[-400:],
            "metrics": extra.get("metrics", {}),
        }
        status_path.write_text(json.dumps(body, indent=2))

    def log(msg: str) -> None:
        prefix = f"run_id={run_id} engine={engine} load={load_name} spec={spec.get('height')}x{spec.get('width')}x{spec.get('frames')}"
        if mlflow_run_id:
            prefix += f" mlflow_run_id={mlflow_run_id}"
        line = f"{prefix} {msg}"
        events.append(line)
        print(line, flush=True)
        flush(mlflow_run_id=mlflow_run_id, mlflow_experiment_id=mlflow_experiment_id)

    def start_stage(name: str) -> None:
        for stage in stages:
            if stage["name"] == name:
                stage["started_at"] = time.time()
                stage["status"] = "running"
        log(f"STAGE_START {name}")
        if observer:
            try:
                observer.start_stage(name)
            except Exception:
                pass
        flush(mlflow_run_id=mlflow_run_id, mlflow_experiment_id=mlflow_experiment_id)

    def end_stage(name: str, ok: bool = True) -> None:
        duration = None
        for stage in stages:
            if stage["name"] == name:
                stage["ended_at"] = time.time()
                stage["status"] = "succeeded" if ok else "failed"
                if stage["started_at"]:
                    duration = stage["ended_at"] - stage["started_at"]
        log(f"STAGE_END {name}" + (f" duration={duration:.2f}s" if duration is not None else ""))
        if observer:
            try:
                observer.end_stage(name)
            except Exception:
                pass
        if mlflow_run_id and duration is not None:
            try:
                import mlflow
                if mlflow.active_run():
                    mlflow.log_metric(f"stage_{name}_s", duration)
            except Exception:
                pass
        flush(mlflow_run_id=mlflow_run_id, mlflow_experiment_id=mlflow_experiment_id)

    flush(state="running")
    log(
        f"START run_id={run_id} engine={payload.get('engine')} "
        f"spec={payload.get('spec')} offload={payload.get('spec', {}).get('offload')}"
    )
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("DO_NOT_TRACK", "1")
    os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.0")
    os.environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", "0.0")

    try:
        metrics_port = int(payload.get("metrics_port") or 8001)
        try:
            from prometheus_client import start_http_server
            start_http_server(metrics_port)
            log(f"metrics listening on :{metrics_port}")
        except OSError as exc:
            log(f"metrics port busy: {exc}")
        except Exception as exc:
            log(f"prometheus_client missing: {exc}")

        try:
            import mlflow
            os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
            os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
            tracking = payload.get("mlflow_tracking_uri") or os.environ.get("MLFLOW_TRACKING_URI")
            if not tracking or tracking.startswith("file:"):
                tracking = f"sqlite:///{ROOT / 'mlflow.db'}"
            mlflow.set_tracking_uri(tracking)
            mlflow.set_experiment("ltx-lab")
            experiment = mlflow.get_experiment_by_name("ltx-lab")
            mlflow_experiment_id = None if experiment is None else experiment.experiment_id
            mlflow.start_run(run_name=run_id)
            mlflow_run_id = mlflow.active_run().info.run_id
            grafana = "http://127.0.0.1:3300"
            console = "http://127.0.0.1:8188"
            mlflow.log_params({
                "engine": engine,
                "load": load_name,
                "height": spec["height"],
                "width": spec["width"],
                "frames": spec["frames"],
                "fps": spec["fps"],
                "seed": spec["seed"],
                "offload": spec.get("offload", "cpu"),
                "video_name": f"{run_id}/output.mp4",
            })
            mlflow.set_tags({
                "run_id": run_id,
                "engine": engine,
                "load": load_name,
                "video_name": f"{run_id}/output.mp4",
                "spec": f"{spec.get('height')}x{spec.get('width')}x{spec.get('frames')}",
                "offload": str(spec.get("offload") or "disk"),
                "grafana_run": f"{grafana}/d/ltx-run-trace?orgId=1&var-run_id={run_id}",
                "grafana_overview": f"{grafana}/d/ltx-overview",
                "console_observe": f"{console}/#observe={run_id}",
            })
            mlflow.log_text(payload["prompt"], "prompt.txt")
            mlflow.log_dict({"run_id": run_id, "engine": engine, "load": load_name, "spec": spec}, "run.json")
            log(f"mlflow run {mlflow_run_id} experiment={mlflow_experiment_id}")
        except Exception as exc:
            log(f"mlflow unavailable: {exc}")

        try:
            from observability.instrument import LTXObserver
            observer = LTXObserver(
                run_id=run_id,
                engine=engine,
                spec=spec,
                mlflow_run_id=mlflow_run_id or "",
                prompt=payload.get("prompt") or "",
                dest=dest,
                load=load_name,
            )
            observer.start_run(payload.get("prompt") or "", engine, spec)
        except Exception as exc:
            log(f"observer unavailable: {exc}")

        if engine == "comfyui":
            return _run_comfy(payload, dest, start_stage, end_stage, log, flush, started, observer)

        start_stage("load")
        import torch
        from ltx_core.model.video_vae.transformer import DiffVAEMode
        from ltx_pipelines.distilled import DistilledPipeline
        from ltx_pipelines.utils.media_io import encode_video, resolve_hdr_color_space, vae_dtype_for_hdr
        from ltx_pipelines.utils.model_paths import ModelPaths
        from ltx_pipelines.utils.types import OffloadMode
        from ltx_core.model.video_vae import get_video_chunks_number

        from lab.hostinfo import capture_host
        from lab.occupancy import weight_paths

        try:
            host = capture_host(engine, spec, load_name)
            (dest / "host.json").write_text(json.dumps(host, indent=2))
            log(
                "host model=%s mem=%s mps=%s torch=%s"
                % (host.get("hw_model"), host.get("memory_bytes"), host.get("mps"), host.get("torch"))
            )
            if mlflow_run_id:
                import mlflow
                if mlflow.active_run():
                    mlflow.log_dict(host, "host.json")
        except Exception as exc:
            log(f"host snapshot skipped: {exc}")

        paths = weight_paths()
        for key, path in paths.items():
            if key == "lora" and engine != "ltx-dfr":
                continue
            if not path.exists():
                raise FileNotFoundError(f"Missing weight {key}: {path}")
        model_paths = ModelPaths.from_split(
            transformer_path=str(paths["transformer"]),
            text_encoder_path=str(paths["text_encoder"]),
            video_vae_path=str(paths["video_vae"]),
            audio_vae_path=str(paths["audio_vae"]),
        )
        offload = {
            "cpu": OffloadMode.CPU,
            "none": OffloadMode.NONE,
            "disk": OffloadMode.DISK,
        }.get(str(payload["spec"].get("offload", "cpu")).lower(), OffloadMode.CPU)
        spec = payload["spec"]
        output_path = Path(payload["output_path"])
        # Distilled CLI runs under inference_mode. Disk streaming loads weights
        # as inference tensors; a grad-enabled forward then raises.
        with torch.inference_mode():
            if engine == "ltx-dfr":
                from ltx_core.loader import LTXV_LORA_COMFY_RENAMING_MAP, LoraPathStrengthAndSDOps
                from ltx_pipelines.dfr_pipeline import DFRPipeline

                pipeline = DFRPipeline(
                    model_paths=model_paths,
                    spatial_upsampler_path=str(paths["upsampler"]),
                    loras=[],
                    detailing_lora=[
                        LoraPathStrengthAndSDOps(str(paths["lora"]), 0.5, LTXV_LORA_COMFY_RENAMING_MAP)
                    ],
                    offload_mode=offload,
                    diffvae_optimization=DiffVAEMode.CHUNKED_EAGER,
                )
            else:
                pipeline = DistilledPipeline(
                    model_paths=model_paths,
                    spatial_upsampler_path=str(paths["upsampler"]),
                    loras=[],
                    offload_mode=offload,
                    diffvae_optimization=DiffVAEMode.CHUNKED_EAGER,
                )
            end_stage("load")

            start_stage("encode")
            end_stage("encode")
            start_stage("generate")
            hdr = resolve_hdr_color_space(images=[], hdr=None)
            vae_dtype = vae_dtype_for_hdr(hdr, torch.bfloat16)
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
                log(
                    "mps allocated=%s driver=%s recommended=%s"
                    % (
                        torch.mps.current_allocated_memory(),
                        torch.mps.driver_allocated_memory(),
                        torch.mps.recommended_max_memory(),
                    )
                )
            # AUTO_TILING plans a min ~80f x 320x320 tile and refuses when MPS
            # usable bytes are under ~2GiB after weights load. Untiled decode of
            # the actual clip (defaults 9x256x384) is smaller than that floor.
            generate_kwargs = {
                "prompt": payload["prompt"],
                "seed": int(spec["seed"]),
                "height": int(spec["height"]),
                "width": int(spec["width"]),
                "num_frames": int(spec["frames"]),
                "frame_rate": int(spec["fps"]),
                "images": [],
                "tiling_config": None,
            }
            if engine != "ltx-dfr":
                generate_kwargs["vae_dtype"] = vae_dtype
                generate_kwargs["color_space"] = hdr
            else:
                generate_kwargs["temporal_upscalings"] = 0
                generate_kwargs["spatial_upscalings"] = 1
            result = pipeline(**generate_kwargs)
            end_stage("generate")

            start_stage("write")
            encode_video(
                video=result.video,
                fps=int(spec["fps"]),
                audio=result.audio,
                output_path=str(output_path),
                video_chunks_number=get_video_chunks_number(result.num_frames, result.tiling_config),
                color_space=hdr,
            )
            digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
            end_stage("write")

        duration = time.time() - started
        log(f"END run_id={run_id} video={output_path} bytes={output_path.stat().st_size} duration={duration:.1f}s")
        if observer:
            observer.end_run(str(output_path), success=True, extra_metrics={"total_duration": duration})
        try:
            import mlflow
            if mlflow.active_run():
                mlflow.log_metric("duration_s", duration)
                mlflow.log_metric("size_bytes", output_path.stat().st_size)
                try:
                    mlflow.log_metric("mps_allocated", float(torch.mps.current_allocated_memory()))
                    mlflow.log_metric("mps_driver", float(torch.mps.driver_allocated_memory()))
                except Exception:
                    pass
                _mlflow_log_artifacts(dest, output_path)
                mlflow.set_tag("status", "succeeded")
                mlflow.end_run()
        except Exception:
            pass
        flush(
            state="succeeded",
            finished_at=time.time(),
            mlflow_run_id=mlflow_run_id,
            mlflow_experiment_id=mlflow_experiment_id,
            sha256=digest,
            metrics={"duration_s": duration, "size_bytes": output_path.stat().st_size},
        )
        return 0
    except Exception as exc:
        err = f"{exc}\n{traceback.format_exc()}"
        log(err)
        for stage in stages:
            if stage["status"] == "running":
                stage["status"] = "failed"
                stage["ended_at"] = time.time()
        try:
            import mlflow
            if mlflow.active_run():
                mlflow.end_run(status="FAILED")
        except Exception:
            pass
        if observer:
            try:
                observer.end_run("", success=False)
            except Exception:
                pass
        flush(state="failed", finished_at=time.time(), error=str(exc), mlflow_run_id=mlflow_run_id)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
