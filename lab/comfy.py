"""Local ComfyUI neighbor: detect, start on :8189, fill an API workflow, queue, fetch mp4.

This repo has no ComfyUI `main.py`. The Carbon console already owns :8188, so Comfy
listens on :8189. `./labctl comfy start` clones ~/Documents/ComfyUI if needed.
`./labctl down` does not stop ComfyUI.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from lab.types import LTX_ROOT, ROOT, VideoSpec

DEFAULT_PORT = 8189
CANDIDATE_PORTS = (8189, 8187, 8190, 8186, 8188)
USER_WORKFLOWS = ROOT / "workflows" / "comfy"
DEFAULT_ROOT = Path.home() / "Documents" / "ComfyUI"
COMFY_REPO = "https://github.com/comfyanonymous/ComfyUI.git"
PID_PATH = ROOT / ".lab" / "comfy.pid"
LOG_PATH = ROOT / ".lab" / "comfy.log"
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
PROMPT_KEYS = ("text", "prompt", "positive", "positive_prompt", "positive_text")
NEGATIVE_MARKERS = ("negative", "neg_prompt", "neg text")
SEED_KEYS = ("seed", "noise_seed")
WIDTH_KEYS = ("width", "image_width")
HEIGHT_KEYS = ("height", "image_height")
FRAME_KEYS = ("length", "num_frames", "frame_count", "frames", "num_frames_total")
FPS_KEYS = ("frame_rate", "fps", "framerate")
PREFIX_KEYS = ("filename_prefix",)
CLIP_TYPES = ("cliptextencode", "gemmaclip", "ltxvtext", "prompt")
LogFn = Callable[[str], None]


class ComfyError(Exception):
    """ComfyUI call failed or the workflow cannot be used."""


def candidate_roots() -> tuple[Path, ...]:
    env = (os.environ.get("COMFYUI_ROOT") or "").strip()
    found: list[Path] = []
    if env:
        found.append(Path(env).expanduser())
    found.extend(
        (
            DEFAULT_ROOT,
            Path.home() / "ComfyUI",
            ROOT.parent / "ComfyUI",
            ROOT / "ComfyUI",
        )
    )
    uniq: list[Path] = []
    seen: set[Path] = set()
    for path in found:
        resolved = path.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        uniq.append(resolved)
    return tuple(uniq)


def install_root() -> Optional[Path]:
    for path in candidate_roots():
        if (path / "main.py").is_file():
            return path
    return None


def desktop_app() -> Optional[Path]:
    for name in ("Comfy Desktop.app", "ComfyUI.app"):
        for folder in (Path("/Applications"), Path.home() / "Applications"):
            path = folder / name
            if path.exists():
                return path
    return None


def how_to_start() -> str:
    root = install_root()
    if root:
        return (
            f"ComfyUI is at {root} but not running. Start it with ./labctl comfy start "
            f"(127.0.0.1:{DEFAULT_PORT}; this lab already uses :8188)."
        )
    app = desktop_app()
    if app:
        return (
            f"Comfy Desktop is at {app}. Start it with ./labctl comfy start so it binds "
            f":{DEFAULT_PORT} instead of :8188."
        )
    return (
        "ComfyUI is not installed, and this lab repo has no main.py. "
        f"Run ./labctl comfy start to clone {DEFAULT_ROOT} and listen on :{DEFAULT_PORT}."
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid() -> Optional[int]:
    if not PID_PATH.exists():
        return None
    try:
        pid = int(PID_PATH.read_text().strip())
    except (OSError, ValueError):
        return None
    if not _pid_alive(pid):
        return None
    return pid


def _write_extra_model_paths(root: Path) -> None:
    dest = root / "extra_model_paths.yaml"
    if dest.exists():
        return
    base = LTX_ROOT / "models" / "ltx-2.5"
    dest.write_text(
        "\n".join(
            [
                "# Point ComfyUI at the LTX-2.5 split weights this lab already downloaded.",
                "ltx-lab:",
                f"    base_path: {base}",
                "    checkpoints: diffusion_models/",
                "    diffusion_models: diffusion_models/",
                "    text_encoders: text_encoders/",
                "    vae: vae/",
                "    loras: loras/",
                "    latent_upscale_models: latent_upscale_models/",
                "",
            ]
        )
    )


def ensure_checkout() -> Path:
    root = install_root()
    if root:
        return root
    dest = Path(os.environ.get("COMFYUI_ROOT") or DEFAULT_ROOT).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not (dest / "main.py").is_file():
        raise ComfyError(f"{dest} exists but has no main.py; set COMFYUI_ROOT to a ComfyUI checkout")
    git = shutil.which("git")
    if not git:
        raise ComfyError("git is not on PATH; install Xcode CLT or clone ComfyUI yourself")
    subprocess.check_call([git, "clone", "--depth", "1", COMFY_REPO, str(dest)])
    return dest


def ensure_venv(root: Path) -> Path:
    python = root / ".venv" / "bin" / "python"
    if python.is_file():
        return python
    py = shutil.which("python3.12") or shutil.which("python3") or sys.executable
    subprocess.check_call([py, "-m", "venv", str(root / ".venv")])
    pip = root / ".venv" / "bin" / "pip"
    subprocess.check_call([str(pip), "install", "-U", "pip", "setuptools", "wheel"])
    req = root / "requirements.txt"
    if not req.exists():
        raise ComfyError(f"ComfyUI requirements missing at {req}")
    subprocess.check_call([str(pip), "install", "-r", str(req)])
    return python


def start(*, timeout_s: float = 180.0) -> dict[str, Any]:
    found = discover()
    if found:
        return {"ok": True, "url": found, "already": True}
    if probe(f"http://127.0.0.1:{DEFAULT_PORT}"):
        return {"ok": True, "url": f"http://127.0.0.1:{DEFAULT_PORT}", "already": True}
    root = install_root()
    app = desktop_app() if root is None else None
    (ROOT / ".lab").mkdir(parents=True, exist_ok=True)
    if root is None and app is None:
        root = ensure_checkout()
    if root:
        python = ensure_venv(root)
        _write_extra_model_paths(root)
        log = open(LOG_PATH, "ab")
        proc = subprocess.Popen(
            [
                str(python),
                "main.py",
                "--listen",
                "127.0.0.1",
                "--port",
                str(DEFAULT_PORT),
                "--disable-auto-launch",
            ],
            cwd=str(root),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        PID_PATH.write_text(str(proc.pid))
        url = f"http://127.0.0.1:{DEFAULT_PORT}"
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if probe(url):
                return {"ok": True, "url": url, "pid": proc.pid, "root": str(root)}
            if proc.poll() is not None:
                tail = LOG_PATH.read_text(errors="replace")[-4000:] if LOG_PATH.exists() else ""
                raise ComfyError(f"ComfyUI exited {proc.returncode}. {tail}")
            time.sleep(1)
        return {
            "ok": False,
            "url": url,
            "pid": proc.pid,
            "root": str(root),
            "error": "started but /system_stats not ready yet; check .lab/comfy.log",
        }
    env = os.environ.copy()
    env["COMFY_PORT"] = str(DEFAULT_PORT)
    env["COMFY_HOST"] = "127.0.0.1"
    subprocess.Popen(["open", str(app)], env=env, start_new_session=True)
    url = f"http://127.0.0.1:{DEFAULT_PORT}"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        found = discover()
        if found:
            return {"ok": True, "url": found, "app": str(app)}
        time.sleep(1)
    return {
        "ok": False,
        "url": url,
        "app": str(app),
        "error": "opened Comfy Desktop; set port to 8189 in Server Config if it bound another port",
    }


def stop() -> dict[str, Any]:
    pid = _read_pid()
    if pid is None:
        return {"ok": True, "stopped": False, "error": "no lab-started ComfyUI pid"}
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not _pid_alive(pid):
            break
        time.sleep(0.2)
    if _pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
    if PID_PATH.exists():
        PID_PATH.unlink()
    return {"ok": True, "stopped": True, "pid": pid}


def base_url() -> str:
    env = (os.environ.get("COMFYUI_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    found = discover()
    return found or f"http://127.0.0.1:{DEFAULT_PORT}"


def looks_like_comfy(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    system = payload.get("system")
    devices = payload.get("devices")
    if isinstance(system, dict) and "devices" in payload:
        return True
    if isinstance(devices, list) and payload.get("system"):
        return True
    return False


def _json(url: str, *, method: str = "GET", body: Optional[dict] = None, timeout: float = 2.0) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return resp.status, None
            try:
                return resp.status, json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            parsed = json.loads(payload.decode("utf-8") or "null")
        except json.JSONDecodeError:
            parsed = payload.decode("utf-8", "replace")
        return exc.code, parsed
    except urllib.error.URLError as exc:
        raise ComfyError(f"ComfyUI is not reachable at {url} ({exc.reason})") from exc


def probe(url: str, timeout: float = 0.6) -> Optional[dict[str, Any]]:
    try:
        code, body = _json(url.rstrip("/") + "/system_stats", timeout=timeout)
    except ComfyError:
        return None
    if code != 200 or not looks_like_comfy(body):
        return None
    return body if isinstance(body, dict) else None


def discover() -> Optional[str]:
    env = (os.environ.get("COMFYUI_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env if probe(env) else None
    for port in CANDIDATE_PORTS:
        url = f"http://127.0.0.1:{port}"
        if probe(url):
            return url
    return None


def workflow_dirs() -> tuple[Path, ...]:
    return (USER_WORKFLOWS, ROOT / "lab" / "comfy" / "workflows")


def _safe_name(name: str) -> str:
    text = str(name or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ComfyError("invalid workflow name")
    if not text.endswith(".json"):
        text += ".json"
    return text


def list_workflows() -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for folder in workflow_dirs():
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name in seen:
                continue
            seen.add(path.name)
            found.append(
                {
                    "id": path.stem,
                    "file": path.name,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "source": "user" if folder == USER_WORKFLOWS else "bundled",
                }
            )
    return found


def load_graph(name: Optional[str] = None) -> tuple[str, dict[str, Any]]:
    workflows = list_workflows()
    if not workflows:
        raise ComfyError(
            "No ComfyUI API workflow on disk. In ComfyUI: File → Export (API), "
            f"then save the JSON into {USER_WORKFLOWS}"
        )
    chosen = None
    if name:
        stem = _safe_name(name).removesuffix(".json")
        chosen = next((item for item in workflows if item["id"] == stem), None)
        if chosen is None:
            raise ComfyError(f"Unknown workflow {stem}. Available: {', '.join(item['id'] for item in workflows)}")
    else:
        chosen = workflows[0]
    path = Path(chosen["path"])
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ComfyError(f"Cannot read workflow {path.name}: {exc}") from exc
    return chosen["id"], as_api_graph(raw)


def as_api_graph(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("prompt"), dict) and raw["prompt"]:
        raw = raw["prompt"]
    if not isinstance(raw, dict) or not raw:
        raise ComfyError("Workflow is empty")
    if "nodes" in raw and "links" in raw:
        raise ComfyError("This is a UI workflow. Export again with File → Export (API).")
    sample = next(iter(raw.values()))
    if not isinstance(sample, dict) or "class_type" not in sample:
        raise ComfyError("Workflow is not ComfyUI API format (each node needs class_type)")
    return json.loads(json.dumps(raw))


def _meta_title(node: dict[str, Any]) -> str:
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    return str(meta.get("title") or node.get("class_type") or "").lower()


def _is_negative(node: dict[str, Any], key: str) -> bool:
    blob = f"{_meta_title(node)} {node.get('class_type', '')} {key}".lower()
    return any(marker in blob for marker in NEGATIVE_MARKERS)


def _is_clip_like(node: dict[str, Any]) -> bool:
    class_type = str(node.get("class_type") or "").lower()
    title = _meta_title(node)
    return any(token in class_type or token in title for token in CLIP_TYPES)


def fill_graph(
    graph: dict[str, Any],
    *,
    prompt: str,
    spec: VideoSpec,
    prefix: str,
) -> dict[str, Any]:
    filled = as_api_graph(graph)
    prompt_hits = 0
    clip_nodes = [
        (node_id, node)
        for node_id, node in filled.items()
        if isinstance(node, dict) and _is_clip_like(node) and not _is_negative(node, "")
    ]
    first_clip = clip_nodes[0][0] if clip_nodes else None
    for node in filled.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key, value in list(inputs.items()):
            lower = key.lower()
            if lower in PROMPT_KEYS and isinstance(value, str):
                if _is_negative(node, key):
                    continue
                if _is_clip_like(node) and first_clip and node is not filled.get(first_clip):
                    title = _meta_title(node)
                    if "prompt" not in title and "positive" not in title:
                        continue
                inputs[key] = prompt
                prompt_hits += 1
            elif lower in SEED_KEYS and isinstance(value, (int, float)):
                inputs[key] = int(spec.seed)
            elif lower in WIDTH_KEYS and isinstance(value, (int, float)):
                inputs[key] = int(spec.width)
            elif lower in HEIGHT_KEYS and isinstance(value, (int, float)):
                inputs[key] = int(spec.height)
            elif lower in FRAME_KEYS and isinstance(value, (int, float)):
                inputs[key] = int(spec.frames)
            elif lower in FPS_KEYS and isinstance(value, (int, float)):
                inputs[key] = int(spec.fps)
            elif lower in PREFIX_KEYS and isinstance(value, str):
                inputs[key] = prefix
    if prompt_hits == 0:
        raise ComfyError("Workflow has no text/prompt input to fill")
    return filled


def _models(url: str, kind: str) -> list[str]:
    try:
        code, body = _json(f"{url}/models/{kind}", timeout=1.2)
    except ComfyError:
        return []
    if code != 200:
        return []
    if isinstance(body, list):
        return [str(item) for item in body]
    return []


def status() -> dict[str, Any]:
    url = (os.environ.get("COMFYUI_BASE_URL") or "").strip().rstrip("/")
    stats = probe(url) if url else None
    if stats is None:
        url = discover()
        stats = probe(url) if url else None
    workflows = list_workflows()
    how = how_to_start()
    if not url or stats is None:
        return {
            "ready": False,
            "url": f"http://127.0.0.1:{DEFAULT_PORT}",
            "ui": f"http://127.0.0.1:{DEFAULT_PORT}",
            "error": "ComfyUI is not running",
            "how": how,
            "workflows": workflows,
            "ltx_models": [],
            "queue": None,
        }
    queue = None
    try:
        code, body = _json(f"{url}/queue", timeout=1.0)
        if code == 200 and isinstance(body, dict):
            queue = {
                "running": len(body.get("queue_running") or []),
                "pending": len(body.get("queue_pending") or []),
            }
    except ComfyError:
        queue = None
    models = []
    for kind in ("checkpoints", "diffusion_models", "loras"):
        models.extend(_models(url, kind))
    ltx_models = [name for name in models if "ltx" in name.lower()]
    ready = bool(workflows)
    blocked = None if ready else (
        f"Export an LTX workflow from ComfyUI (File → Export (API)) into {USER_WORKFLOWS}"
    )
    system = stats.get("system") if isinstance(stats.get("system"), dict) else {}
    return {
        "ready": ready,
        "url": url,
        "ui": url,
        "error": blocked,
        "how": (
            f"Open {url} for the graph editor. Export File → Export (API) into {USER_WORKFLOWS}."
            if not ready
            else f"Open {url} for the graph editor. This lab queues the filled API workflow."
        ),
        "comfy_version": system.get("comfyui_version") or system.get("version"),
        "python": system.get("python_version"),
        "pytorch": system.get("pytorch_version"),
        "argv": system.get("argv"),
        "devices": stats.get("devices") or [],
        "queue": queue,
        "workflows": workflows,
        "ltx_models": ltx_models[:40],
        "model_hint": (ltx_models[0] if ltx_models else None),
    }


def queue_prompt(graph: dict[str, Any], *, client_id: str, prompt_id: str) -> str:
    url = base_url()
    payload = {"prompt": graph, "client_id": client_id, "prompt_id": prompt_id}
    code, body = _json(f"{url}/prompt", method="POST", body=payload, timeout=10)
    if code != 200 or not isinstance(body, dict):
        error = body
        if isinstance(body, dict):
            error = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
            error = error or body
        raise ComfyError(f"ComfyUI rejected the workflow: {error}")
    return str(body.get("prompt_id") or prompt_id)


def history(prompt_id: str) -> Optional[dict[str, Any]]:
    url = base_url()
    code, body = _json(f"{url}/history/{urllib.parse.quote(prompt_id)}", timeout=5)
    if code != 200 or not isinstance(body, dict):
        return None
    return body.get(prompt_id) or (body if body.get("outputs") else None)


def interrupt() -> dict[str, Any]:
    url = base_url()
    try:
        _json(f"{url}/interrupt", method="POST", body={}, timeout=3)
    except ComfyError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "url": url}


def _output_files(entry: dict[str, Any]) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    outputs = entry.get("outputs") if isinstance(entry.get("outputs"), dict) else {}
    for node_out in outputs.values():
        if not isinstance(node_out, dict):
            continue
        for key in ("gifs", "videos", "images", "audio"):
            items = node_out.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("filename") or "")
                suffix = Path(name).suffix.lower()
                if key == "images" and suffix not in VIDEO_SUFFIXES:
                    continue
                if not name:
                    continue
                files.append(
                    {
                        "filename": name,
                        "subfolder": str(item.get("subfolder") or ""),
                        "type": str(item.get("type") or "output"),
                    }
                )
    return files


def fetch_file(info: dict[str, str], dest: Path) -> Path:
    url = base_url()
    query = urllib.parse.urlencode(
        {
            "filename": info["filename"],
            "subfolder": info.get("subfolder") or "",
            "type": info.get("type") or "output",
        }
    )
    req = urllib.request.Request(f"{url}/view?{query}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return dest


def wait_for_output(
    prompt_id: str,
    *,
    timeout_s: float = 60 * 60,
    log: Optional[LogFn] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    started = time.time()
    while True:
        if should_stop and should_stop():
            raise ComfyError("cancelled")
        entry = history(prompt_id)
        if entry:
            status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
            if status.get("status_str") == "error":
                raise ComfyError(f"ComfyUI execution failed: {status}")
            files = _output_files(entry)
            completed = bool(status.get("completed")) or bool(files)
            if completed and files:
                return entry
            if completed and not files:
                raise ComfyError("ComfyUI finished without a video output (expected mp4/webm in Save/Combine node)")
        if time.time() - started > timeout_s:
            raise ComfyError(f"Timed out waiting for ComfyUI prompt {prompt_id}")
        if log:
            log(f"waiting on ComfyUI prompt_id={prompt_id}")
        time.sleep(2)


def run_job(
    *,
    prompt: str,
    spec: VideoSpec,
    dest: Path,
    workflow: Optional[str] = None,
    run_id: str,
    log: Optional[LogFn] = None,
    on_stage: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    def emit(msg: str) -> None:
        if log:
            log(msg)

    info = status()
    if not info.get("ready"):
        raise ComfyError(info.get("error") or "ComfyUI is not ready")
    name, graph = load_graph(workflow)
    prefix = f"ltx-lab/{run_id}"
    filled = fill_graph(graph, prompt=prompt, spec=spec, prefix=prefix)
    (dest / "comfy.workflow.json").write_text(json.dumps(filled, indent=2))
    client_id = uuid.uuid4().hex
    prompt_id = uuid.uuid4().hex
    if on_stage:
        on_stage("encode")
    queued_id = queue_prompt(filled, client_id=client_id, prompt_id=prompt_id)
    pack = {
        "url": info.get("url"),
        "workflow": name,
        "prompt_id": queued_id,
        "client_id": client_id,
        "prefix": prefix,
    }
    (dest / "comfy.json").write_text(json.dumps(pack, indent=2))
    emit(f"queued ComfyUI prompt_id={queued_id} workflow={name} url={info.get('url')}")
    if on_stage:
        on_stage("generate")
    entry = wait_for_output(queued_id, log=emit)
    files = _output_files(entry)
    video = next((item for item in files if Path(item["filename"]).suffix.lower() in VIDEO_SUFFIXES), None)
    if video is None:
        raise ComfyError("ComfyUI produced no mp4/webm")
    if on_stage:
        on_stage("write")
    output = dest / "output.mp4"
    fetch_file(video, output)
    pack["artifact"] = video
    pack["bytes"] = output.stat().st_size
    (dest / "comfy.json").write_text(json.dumps(pack, indent=2))
    emit(f"fetched {video['filename']} -> {output} bytes={pack['bytes']}")
    return pack
