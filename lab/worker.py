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

    def flush(**extra):
        body = {
            "run_id": run_id,
            "state": extra.get("state", "running"),
            "started_at": started,
            "finished_at": extra.get("finished_at"),
            "error": extra.get("error"),
            "mlflow_run_id": extra.get("mlflow_run_id"),
            "sha256": extra.get("sha256"),
            "stages": stages,
            "events": events[-400:],
            "metrics": extra.get("metrics", {}),
        }
        status_path.write_text(json.dumps(body, indent=2))

    def log(msg: str) -> None:
        events.append(msg)
        print(msg, flush=True)
        flush()

    def start_stage(name: str) -> None:
        for stage in stages:
            if stage["name"] == name:
                stage["started_at"] = time.time()
                stage["status"] = "running"
        log(f"STAGE_START {name}")
        flush()

    def end_stage(name: str, ok: bool = True) -> None:
        for stage in stages:
            if stage["name"] == name:
                stage["ended_at"] = time.time()
                stage["status"] = "succeeded" if ok else "failed"
        log(f"STAGE_END {name}")
        flush()

    flush(state="running")
    log(
        f"START run_id={run_id} engine={payload.get('engine')} "
        f"spec={payload.get('spec')} offload={payload.get('spec', {}).get('offload')}"
    )
    os.environ.setdefault("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "0.0")
    os.environ.setdefault("PYTORCH_MPS_LOW_WATERMARK_RATIO", "0.0")

    mlflow_run_id = None
    observer = None
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
            mlflow.start_run(run_name=run_id)
            mlflow_run_id = mlflow.active_run().info.run_id
            spec = payload["spec"]
            mlflow.log_params({
                "engine": payload.get("engine"),
                "height": spec["height"],
                "width": spec["width"],
                "frames": spec["frames"],
                "fps": spec["fps"],
                "seed": spec["seed"],
                "offload": spec.get("offload", "cpu"),
            })
            mlflow.log_text(payload["prompt"], "prompt.txt")
            log(f"mlflow run {mlflow_run_id}")
        except Exception as exc:
            log(f"mlflow unavailable: {exc}")

        try:
            from observability.instrument import LTXObserver
            observer = LTXObserver()
            observer.start_run(payload["prompt"], payload.get("engine", "ltx-distilled"), payload["spec"])
        except Exception as exc:
            log(f"observer unavailable: {exc}")

        start_stage("load")
        import torch
        from ltx_core.model.video_vae.transformer import DiffVAEMode
        from ltx_pipelines.distilled import DistilledPipeline
        from ltx_pipelines.utils.media_io import encode_video, resolve_hdr_color_space, vae_dtype_for_hdr
        from ltx_pipelines.utils.model_paths import ModelPaths
        from ltx_pipelines.utils.types import OffloadMode
        from ltx_core.model.video_vae import get_video_chunks_number

        from lab.occupancy import weight_paths

        paths = weight_paths()
        for key, path in paths.items():
            if key == "lora":
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
            if observer:
                observer.start_stage("generate")
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
            result = pipeline(
                prompt=payload["prompt"],
                seed=int(spec["seed"]),
                height=int(spec["height"]),
                width=int(spec["width"]),
                num_frames=int(spec["frames"]),
                frame_rate=int(spec["fps"]),
                images=[],
                vae_dtype=vae_dtype,
                color_space=hdr,
                tiling_config=None,
            )
            if observer:
                observer.end_stage("generate")
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
                mlflow.log_artifact(str(output_path), artifact_path="video")
                mlflow.end_run()
        except Exception:
            pass
        flush(state="succeeded", finished_at=time.time(), mlflow_run_id=mlflow_run_id, sha256=digest, metrics={"duration_s": duration})
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
