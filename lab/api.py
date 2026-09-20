from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from lab.runtime import Lab, _write_pid
from lab.types import (
    ROOT,
    EngineBlocked,
    GenerationRequest,
    LabBusy,
    OccupancyError,
    SpecError,
)
from lab.omlx import OmlxError

CONSOLE_DIST = ROOT / "lab-console" / "dist"


def make_handler(lab: Lab):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ltx-lab-api/1.0"

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _cors(self) -> None:
            origin = self.headers.get("Origin", "http://127.0.0.1:8188")
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")

        def _json(self, code: int, payload) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, code: int, data: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self._cors()
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._do_GET()
            except Exception as exc:
                try:
                    self._json(500, {"error": str(exc)})
                except Exception:
                    pass

        def _do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            if path in {"/metrics", "/api/metrics"}:
                body = lab.metrics_text().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self._cors()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path in {"/api/health"}:
                self._json(200, {"ok": True, "root": str(ROOT)})
                return
            if path in {"/api/lab/status", "/api/status"}:
                try:
                    self._json(200, lab.readiness().to_dict())
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return
            if path == "/api/omlx":
                try:
                    self._json(200, lab.omlx_status())
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return
            if path == "/api/engines":
                self._json(200, {"engines": [e.to_dict() for e in lab.engines()]})
                return
            if path == "/api/links":
                self._json(200, lab.links().to_dict())
                return
            if path == "/api/actions":
                self._json(200, {"actions": [a.to_dict() for a in lab.actions()]})
                return
            if path == "/api/runs":
                try:
                    self._json(200, {"runs": [r.to_dict() for r in lab.list_runs()]})
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return
            if path == "/api/references":
                from lab import ledger
                self._json(200, {"references": ledger.list_pins()})
                return
            if path.startswith("/api/runs/") and path.endswith("/observe"):
                run_id = path.split("/")[3]
                try:
                    self._json(200, lab.observe(run_id))
                except FileNotFoundError:
                    self._json(404, {"error": "run not found"})
                return
            if path.startswith("/api/runs/") and path.endswith("/video"):
                run_id = path.split("/")[3]
                run = lab.get(run_id)
                if not run or not run.artifact:
                    self._json(404, {"error": "video not found"})
                    return
                data = Path(run.artifact.path).read_bytes()
                self._bytes(200, data, "video/mp4")
                return
            if path.startswith("/api/runs/") and path.endswith("/log"):
                run_id = path.split("/")[3]
                log_path = ROOT / "runs" / run_id / "worker.log"
                tail = int(qs.get("tail", ["400"])[0])
                text = ""
                if log_path.exists():
                    lines = log_path.read_text(errors="replace").splitlines()
                    text = "\n".join(lines[-tail:])
                run = lab.get(run_id)
                self._json(200, {"log": text, "state": None if run is None else run.state.value})
                return
            if path.startswith("/api/runs/"):
                run_id = path.split("/")[3]
                run = lab.get(run_id)
                if run is None:
                    self._json(404, {"error": "run not found"})
                    return
                self._json(200, run.to_dict())
                return
            if path.startswith("/api/references/") and path.endswith("/video"):
                pin_id = path.split("/")[3]
                video = ROOT / "references" / pin_id / "output.mp4"
                if not video.exists():
                    self._json(404, {"error": "reference video not found"})
                    return
                self._bytes(200, video.read_bytes(), "video/mp4")
                return
            self._serve_static(path)

        def do_POST(self) -> None:  # noqa: N802
            try:
                self._do_POST()
            except Exception as exc:
                try:
                    self._json(500, {"error": str(exc)})
                except Exception:
                    pass

        def _do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            if path == "/api/omlx/rewrite":
                try:
                    prompt = str(body.get("prompt") or "")
                    model = body.get("model")
                    self._json(200, lab.rewrite_prompt(prompt, model=model))
                except OmlxError as exc:
                    self._json(503, {"error": str(exc)})
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return
            if path == "/api/omlx/cache/clear":
                try:
                    self._json(200, lab.start_action("omlx_clear_cache", confirm=True))
                except OmlxError as exc:
                    self._json(503, {"error": str(exc)})
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return
            if path == "/api/generate":
                try:
                    request = GenerationRequest.from_dict(body)
                    run = lab.generate(request)
                    self._json(202, run.to_dict())
                except LabBusy as exc:
                    self._json(409, {"error": str(exc)})
                except (EngineBlocked, SpecError) as exc:
                    self._json(400, {"error": str(exc)})
                except OccupancyError as exc:
                    self._json(503, {"error": str(exc)})
                except Exception as exc:
                    self._json(500, {"error": str(exc)})
                return
            if path.startswith("/api/runs/") and path.endswith("/cancel"):
                run_id = path.split("/")[3]
                try:
                    self._json(200, lab.cancel(run_id).to_dict())
                except FileNotFoundError:
                    self._json(404, {"error": "run not found"})
                return
            if path.startswith("/api/runs/") and path.endswith("/pin"):
                run_id = path.split("/")[3]
                label = str(body.get("label") or "reference")
                try:
                    pin = lab.pin(run_id, label)
                    self._json(200, pin.to_dict())
                except (FileNotFoundError, ValueError) as exc:
                    self._json(400, {"error": str(exc)})
                return
            if path.startswith("/api/actions/"):
                action_id = path.split("/")[3]
                try:
                    result = lab.start_action(action_id, confirm=bool(body.get("confirm")))
                    self._json(200, result)
                except PermissionError as exc:
                    self._json(400, {"error": str(exc), "confirm_required": True})
                except KeyError:
                    self._json(404, {"error": "unknown action"})
                return
            self._json(404, {"error": "not found"})

        def _serve_static(self, path: str) -> None:
            if not CONSOLE_DIST.exists():
                self._json(404, {"error": "console not built; use Vite on :8188"})
                return
            rel = "index.html" if path == "/" else path.lstrip("/")
            file_path = (CONSOLE_DIST / rel).resolve()
            if CONSOLE_DIST.resolve() not in file_path.parents and file_path != CONSOLE_DIST.resolve():
                self._json(403, {"error": "forbidden"})
                return
            if not file_path.exists() or file_path.is_dir():
                file_path = CONSOLE_DIST / "index.html"
            data = file_path.read_bytes()
            ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            self._bytes(200, data, ctype)

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8199) -> None:
    lab = Lab.open()
    httpd = ThreadingHTTPServer((host, port), make_handler(lab))
    _write_pid("api", os.getpid())
    print(f"LTX lab API on http://{host}:{port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
