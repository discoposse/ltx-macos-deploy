from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lab import comfy
from lab.types import VideoSpec


def _graph() -> dict:
    return {
        "1": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "old positive"},
            "_meta": {"title": "Positive"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "keep negative"},
            "_meta": {"title": "Negative prompt"},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "style lock"},
            "_meta": {"title": "Style"},
        },
        "4": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {"width": 512, "height": 512, "length": 17},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {"seed": 1, "filename": "keep-me.mp4", "filename_prefix": "ComfyUI"},
        },
        "6": {
            "class_type": "LTXVScheduler",
            "inputs": {"frame_rate": 8},
        },
    }


class ComfyGraphTests(unittest.TestCase):
    def test_looks_like_comfy_requires_system_stats_shape(self) -> None:
        self.assertTrue(comfy.looks_like_comfy({"system": {"os": "darwin"}, "devices": []}))
        self.assertFalse(comfy.looks_like_comfy("<!doctype html>"))
        self.assertFalse(comfy.looks_like_comfy({"ok": True}))
        self.assertFalse(comfy.looks_like_comfy({"system": "up"}))

    def test_as_api_graph_unwraps_prompt_and_rejects_ui_export(self) -> None:
        graph = _graph()
        self.assertEqual(comfy.as_api_graph({"prompt": graph})["1"]["class_type"], "CLIPTextEncode")
        with self.assertRaises(comfy.ComfyError) as ui:
            comfy.as_api_graph({"nodes": [], "links": []})
        self.assertIn("UI workflow", str(ui.exception))
        with self.assertRaises(comfy.ComfyError):
            comfy.as_api_graph({"1": {"inputs": {"text": "no class"}}})

    def test_fill_graph_writes_prompt_seed_spec_and_prefix(self) -> None:
        spec = VideoSpec(height=256, width=384, frames=9, fps=24, seed=99, offload="disk")
        filled = comfy.fill_graph(_graph(), prompt="a red hatchback", spec=spec, prefix="ltx-lab/run-1")
        self.assertEqual(filled["1"]["inputs"]["text"], "a red hatchback")
        self.assertEqual(filled["2"]["inputs"]["text"], "keep negative")
        self.assertEqual(filled["3"]["inputs"]["text"], "style lock")
        self.assertEqual(filled["4"]["inputs"]["width"], 384)
        self.assertEqual(filled["4"]["inputs"]["height"], 256)
        self.assertEqual(filled["4"]["inputs"]["length"], 9)
        self.assertEqual(filled["5"]["inputs"]["seed"], 99)
        self.assertEqual(filled["5"]["inputs"]["filename"], "keep-me.mp4")
        self.assertEqual(filled["5"]["inputs"]["filename_prefix"], "ltx-lab/run-1")
        self.assertEqual(filled["6"]["inputs"]["frame_rate"], 24)

    def test_fill_graph_requires_a_prompt_input(self) -> None:
        graph = {
            "1": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }
        with self.assertRaises(comfy.ComfyError) as exc:
            comfy.fill_graph(graph, prompt="x", spec=VideoSpec(256, 384, 9, 24, 1, "disk"), prefix="p")
        self.assertIn("no text/prompt", str(exc.exception))

    def test_safe_name_rejects_path_escape(self) -> None:
        for name in ("../secret", "..", ".", "foo/bar", "foo\\bar", ""):
            with self.assertRaises(comfy.ComfyError):
                comfy._safe_name(name)

    def test_load_graph_reads_user_export_and_rejects_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "ltx-distilled.json").write_text(json.dumps(_graph()))
            with patch.object(comfy, "USER_WORKFLOWS", folder), patch.object(comfy, "workflow_dirs", lambda: (folder,)):
                name, graph = comfy.load_graph("ltx-distilled")
                self.assertEqual(name, "ltx-distilled")
                self.assertEqual(graph["1"]["class_type"], "CLIPTextEncode")
                listed = comfy.list_workflows()
                self.assertEqual(listed[0]["id"], "ltx-distilled")
                self.assertEqual(listed[0]["source"], "user")
                with self.assertRaises(comfy.ComfyError) as exc:
                    comfy.load_graph("missing")
                self.assertIn("Unknown workflow", str(exc.exception))

    def test_how_to_start_when_missing(self) -> None:
        with patch.object(comfy, "install_root", return_value=None), patch.object(comfy, "desktop_app", return_value=None):
            text = comfy.how_to_start()
        self.assertIn("./labctl comfy start", text)
        self.assertIn("no main.py", text)

    def test_install_root_finds_checkout(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("print('comfy')\n")
            with patch.object(comfy, "candidate_roots", return_value=(root,)):
                self.assertEqual(comfy.install_root(), root)


if __name__ == "__main__":
    unittest.main()
