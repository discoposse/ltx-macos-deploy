#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lab.runtime import Lab, _write_pid, ensure_console_build
from lab.types import DEFAULT_PROMPT, DEFAULT_SPEC, EngineId, GenerationRequest, LTX_BAND, ROOT as LAB_ROOT


def cmd_up(_: argparse.Namespace) -> int:
    lab = Lab.open()
    readiness = lab.up()
    _start_api(lab)
    _start_console()
    print(json.dumps(lab.links().to_dict(), indent=2))
    print(f"readiness: {lab.readiness().state.value}")
    blockers = lab.readiness().blockers()
    if blockers:
        for item in blockers:
            print(f"  blocked: {item.label} — {item.detail}")
    print(f"Open {lab.links().console}")
    return 0 if not blockers else 0


def cmd_down(_: argparse.Namespace) -> int:
    Lab.open().down()
    print("LTX lab stopped. Other local labs were not touched.")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    print(json.dumps(Lab.open().readiness().to_dict(), indent=2))
    return 0


def cmd_url(args: argparse.Namespace) -> int:
    links = Lab.open().links().to_dict()
    key = args.name
    if key not in links:
        print(f"unknown url {key}; choose from {', '.join(links)}", file=sys.stderr)
        return 2
    print(links[key])
    return 0


def cmd_omlx(args: argparse.Namespace) -> int:
    from lab import omlx

    cmd = args.omlx_cmd or "status"
    if cmd == "rewrite":
        print(json.dumps(omlx.rewrite(args.prompt, model=getattr(args, "model", None)), indent=2))
        return 0
    if cmd == "snapshot":
        print(json.dumps(omlx.snapshot(model=getattr(args, "model", None), prompt=getattr(args, "prompt", None), do_probe=True), indent=2))
        return 0
    if cmd == "clear-cache":
        print(json.dumps(omlx.clear_cache(), indent=2))
        return 0
    info = omlx.status()
    print(json.dumps(info, indent=2))
    return 0 if info.get("ready") else 1


def cmd_comfy(args: argparse.Namespace) -> int:
    from lab import comfy

    cmd = args.comfy_cmd or "status"
    if cmd == "interrupt":
        print(json.dumps(comfy.interrupt(), indent=2))
        return 0
    if cmd == "stop":
        print(json.dumps(comfy.stop(), indent=2))
        return 0
    if cmd == "start":
        try:
            result = comfy.start()
        except comfy.ComfyError as exc:
            print(json.dumps({"ok": False, "error": str(exc), "how": comfy.how_to_start()}, indent=2))
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if cmd == "models":
        print(json.dumps(comfy.link_template_models(), indent=2))
        return 0
    info = comfy.status()
    print(json.dumps(info, indent=2))
    return 0 if info.get("running") or info.get("ready") else 1


def cmd_generate(args: argparse.Namespace) -> int:
    from lab.types import PROOF_SPEC

    lab = Lab.open()
    spec = PROOF_SPEC if args.smoke else DEFAULT_SPEC
    request = GenerationRequest(
        prompt=args.prompt or DEFAULT_PROMPT,
        engine=EngineId(args.engine),
        spec=spec,
        workflow=getattr(args, "workflow", None),
    )
    run = lab.generate(request)
    if run.state.value == "queued":
        print(f"queued {run.id} (worker busy; starts when the current clip finishes)")
    else:
        print(f"queued {run.id}")
    if args.wait:
        run = lab.wait(run.id)
        print(json.dumps(run.to_dict(), indent=2))
        return 0 if run.state.value == "succeeded" else 1
    return 0


def cmd_pin(args: argparse.Namespace) -> int:
    pin = Lab.open().pin(args.run_id, args.label)
    print(json.dumps(pin.to_dict(), indent=2))
    return 0


def cmd_storage(_: argparse.Namespace) -> int:
    print(json.dumps(Lab.open().storage(), indent=2))
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    print(json.dumps(Lab.open().delete_run(args.run_id), indent=2))
    return 0


def cmd_reclaim(args: argparse.Namespace) -> int:
    result = Lab.open().reclaim(keep=args.keep, keep_pinned=not args.include_pinned)
    print(json.dumps(result, indent=2))
    return 0


def _start_api(lab: Lab) -> None:
    from lab.occupancy import port_open
    if port_open(lab.ports["lab_api"]):
        return
    (LAB_ROOT / ".lab").mkdir(parents=True, exist_ok=True)
    log = open(LAB_ROOT / ".lab" / "api.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "lab.api"],
        cwd=str(LAB_ROOT),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={**os.environ, "PYTHONPATH": str(LAB_ROOT)},
    )
    _write_pid("api", proc.pid)
    for _ in range(40):
        if port_open(lab.ports["lab_api"]):
            return
        time.sleep(0.2)


def _start_console() -> None:
    from lab.occupancy import port_open
    port = LTX_BAND["console"]
    if port_open(port):
        return
    ensure_console_build()
    if port_open(port):
        return
    console = LAB_ROOT / "lab-console"
    if not (console / "node_modules").exists():
        try:
            subprocess.check_call(["npm", "install"], cwd=str(console))
        except Exception as exc:
            print(f"console not built and npm install failed ({exc}). Open http://127.0.0.1:8199 after a local build.", file=sys.stderr)
            return
        ensure_console_build()
        if port_open(port):
            return
    log = open(LAB_ROOT / ".lab" / "console.log", "w")
    env = os.environ.copy()
    env["PORT"] = str(port)
    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(console),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    _write_pid("console", proc.pid)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lab", description="LTX mini lab")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up").set_defaults(func=cmd_up)
    sub.add_parser("down").set_defaults(func=cmd_down)
    sub.add_parser("status").set_defaults(func=cmd_status)
    url = sub.add_parser("url")
    url.add_argument("name", choices=["console", "grafana", "prometheus", "mlflow", "metrics", "loki", "omlx", "comfy"])
    url.set_defaults(func=cmd_url)
    omlx_p = sub.add_parser("omlx", help="oMLX prompt rewrite status")
    omlx_sub = omlx_p.add_subparsers(dest="omlx_cmd")
    omlx_p.set_defaults(func=cmd_omlx, omlx_cmd="status")
    omlx_sub.add_parser("status")
    rewrite = omlx_sub.add_parser("rewrite")
    rewrite.add_argument("prompt")
    rewrite.add_argument("--model")
    snap = omlx_sub.add_parser("snapshot")
    snap.add_argument("prompt", nargs="?")
    snap.add_argument("--model")
    omlx_sub.add_parser("clear-cache")
    comfy_p = sub.add_parser("comfy", help="ComfyUI neighbor status")
    comfy_sub = comfy_p.add_subparsers(dest="comfy_cmd")
    comfy_p.set_defaults(func=cmd_comfy, comfy_cmd="status")
    comfy_sub.add_parser("status")
    comfy_sub.add_parser("start", help="Clone ~/Documents/ComfyUI if needed and listen on :8189")
    comfy_sub.add_parser("stop", help="Stop a ComfyUI process started by this lab")
    comfy_sub.add_parser("interrupt")
    comfy_sub.add_parser("models", help="Move Comfy LTX template weights from ~/Downloads into ComfyUI/models/")
    gen = sub.add_parser("generate")
    gen.add_argument("prompt", nargs="?")
    gen.add_argument("--engine", default="ltx-distilled")
    gen.add_argument("--workflow", help="ComfyUI API workflow name from workflows/comfy/")
    gen.add_argument("--smoke", action="store_true", help="17-frame proof spec")
    gen.add_argument("--wait", action="store_true")
    gen.set_defaults(func=cmd_generate)
    pin = sub.add_parser("pin")
    pin.add_argument("run_id")
    pin.add_argument("--label", default="reference")
    pin.set_defaults(func=cmd_pin)
    sub.add_parser("storage", help="Show disk used by runs and pins").set_defaults(func=cmd_storage)
    rm = sub.add_parser("rm", help="Delete one finished run directory")
    rm.add_argument("run_id")
    rm.set_defaults(func=cmd_rm)
    reclaim = sub.add_parser("reclaim", help="Delete older unpinned runs to free disk")
    reclaim.add_argument("--keep", type=int, default=5, help="Keep this many newest unpinned runs")
    reclaim.add_argument("--include-pinned", action="store_true", help="Also delete pinned runs (references stay)")
    reclaim.set_defaults(func=cmd_reclaim)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
