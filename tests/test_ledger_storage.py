from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lab import ledger
from lab.types import EngineId, GenerationRequest, Run, RunState, RunTrace, VideoSpec


def _run(run_id: str, *, state: RunState, created_at: float, pinned: bool = False, prompt: str = "a clip") -> Run:
    return Run(
        id=run_id,
        request=GenerationRequest(
            prompt=prompt,
            engine=EngineId.ltx_distilled,
            spec=VideoSpec(256, 384, 9, 24, 42, "disk"),
        ),
        state=state,
        created_at=created_at,
        pinned=pinned,
        trace=RunTrace(run_id=run_id, stages=ledger.new_stages()),
    )


class LedgerStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.runs = root / "runs"
        self.refs = root / "references"
        self.runs.mkdir()
        self.refs.mkdir()
        self.patches = [
            patch.object(ledger, "RUNS_DIR", self.runs),
            patch.object(ledger, "REFS_DIR", self.refs),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def _write(self, run: Run, payload: bytes = b"mp4") -> None:
        dest = ledger.run_dir(run.id)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "output.mp4").write_bytes(payload)
        ledger.save_run(run)

    def test_delete_refuses_active_run(self) -> None:
        run = _run("keep-running", state=RunState.running, created_at=1)
        self._write(run)
        with self.assertRaises(ValueError):
            ledger.delete_run(run.id)
        self.assertTrue(ledger.run_dir(run.id).exists())

    def test_delete_refuses_path_escape(self) -> None:
        with self.assertRaises(ValueError):
            ledger.delete_run("../secret")

    def test_reclaim_keeps_newest_and_pinned(self) -> None:
        now = time.time()
        self._write(_run("old-fail", state=RunState.failed, created_at=now - 40), b"a" * 10)
        self._write(_run("mid-ok", state=RunState.succeeded, created_at=now - 30), b"b" * 20)
        self._write(_run("pin-ok", state=RunState.succeeded, created_at=now - 20, pinned=True), b"c" * 30)
        self._write(_run("new-ok", state=RunState.succeeded, created_at=now - 10), b"d" * 40)
        self._write(_run("live", state=RunState.running, created_at=now), b"e" * 50)
        result = ledger.reclaim(keep=1, keep_pinned=True)
        ids = set(ledger.list_run_ids())
        self.assertIn("new-ok", ids)
        self.assertIn("pin-ok", ids)
        self.assertIn("live", ids)
        self.assertNotIn("old-fail", ids)
        self.assertNotIn("mid-ok", ids)
        self.assertEqual(result["deleted_count"], 2)
        self.assertGreater(result["freed_bytes"], 0)

    def test_next_queued_is_oldest_first(self) -> None:
        now = time.time()
        self._write(_run("q2", state=RunState.queued, created_at=now + 2, prompt="second"))
        self._write(_run("q1", state=RunState.queued, created_at=now + 1, prompt="first"))
        nxt = ledger.next_queued()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.id, "q1")

    def test_storage_counts_bytes(self) -> None:
        self._write(_run("clip", state=RunState.succeeded, created_at=1), b"hello-world")
        snap = ledger.storage_snapshot()
        self.assertGreaterEqual(snap["runs_bytes"], len(b"hello-world"))
        self.assertEqual(snap["run_count"], 1)
        self.assertEqual(snap["runs"][0]["id"], "clip")

    def test_delete_pin_clears_run_flag(self) -> None:
        run = _run("pinned-clip", state=RunState.succeeded, created_at=1, pinned=True)
        self._write(run, b"video")
        pin_dir = self.refs / "pinned-clip-ref"
        pin_dir.mkdir()
        (pin_dir / "output.mp4").write_bytes(b"video")
        (pin_dir / "pin.json").write_text(
            json.dumps({"id": pin_dir.name, "run_id": run.id, "label": "ref"})
        )
        result = ledger.delete_pin(pin_dir.name)
        self.assertFalse(pin_dir.exists())
        self.assertEqual(result["kind"], "reference")
        reloaded = ledger.load_run(run.id)
        self.assertIsNotNone(reloaded)
        self.assertFalse(reloaded.pinned)


if __name__ == "__main__":
    unittest.main()
