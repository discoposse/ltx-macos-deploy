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

from lab.runtime import Lab, _write_pid
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


def cmd_generate(args: argparse.Namespace) -> int:
    from lab.types import PROOF_SPEC

    lab = Lab.open()
    spec = PROOF_SPEC if args.smoke else DEFAULT_SPEC
    request = GenerationRequest(
        prompt=args.prompt or DEFAULT_PROMPT,
        engine=EngineId(args.engine),
        spec=spec,
    )
    run = lab.generate(request)
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


def _start_api(lab: Lab) -> None:
    if __import__("lab.occupancy", fromlist=["port_open"]).port_open(lab.ports["lab_api"]):
        return
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
    for _ in range(20):
        if __import__("lab.occupancy", fromlist=["port_open"]).port_open(lab.ports["lab_api"]):
            return
        time.sleep(0.2)


def _start_console() -> None:
    from lab.occupancy import port_open
    port = LTX_BAND["console"]
    if port_open(port):
        return
    console = LAB_ROOT / "lab-console"
    if not (console / "node_modules").exists():
        subprocess.check_call(["npm", "install"], cwd=str(console))
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
    url.add_argument("name", choices=["console", "grafana", "prometheus", "mlflow", "metrics", "loki"])
    url.set_defaults(func=cmd_url)
    gen = sub.add_parser("generate")
    gen.add_argument("prompt", nargs="?")
    gen.add_argument("--engine", default="ltx-distilled")
    gen.add_argument("--smoke", action="store_true", help="17-frame proof spec")
    gen.add_argument("--wait", action="store_true")
    gen.set_defaults(func=cmd_generate)
    pin = sub.add_parser("pin")
    pin.add_argument("run_id")
    pin.add_argument("--label", default="reference")
    pin.set_defaults(func=cmd_pin)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
