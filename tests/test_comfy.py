from __future__ import annotations

import json
import os
import unittest
import uuid
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

    def test_queue_prompt_sends_canonical_hyphenated_uuid(self) -> None:
        sent: dict = {}

        def fake_json(url, method="GET", body=None, timeout=1.0):
            sent["body"] = body
            return 200, {"prompt_id": body["prompt_id"]}

        hex_id = uuid.uuid4().hex
        self.assertNotIn("-", hex_id)
        with patch.object(comfy, "_json", side_effect=fake_json), patch.object(
            comfy, "base_url", return_value="http://127.0.0.1:8189"
        ):
            queued = comfy.queue_prompt({"1": {"class_type": "NoOp", "inputs": {}}}, client_id="lab", prompt_id=hex_id)
        canonical = str(uuid.UUID(hex_id))
        self.assertEqual(sent["body"]["prompt_id"], canonical)
        self.assertEqual(queued, canonical)
        self.assertEqual(str(uuid.UUID(queued)), queued)

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

    def test_link_template_models_moves_from_downloads(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            downloads = home / "Downloads"
            root = Path(tmp) / "ComfyUI"
            downloads.mkdir(parents=True)
            src = downloads / "gemma4_e2b_it_int8_convrot.safetensors"
            payload = b"x" * 2_000_000
            src.write_bytes(payload)
            with patch.object(comfy, "install_root", return_value=root), patch.object(Path, "home", return_value=home):
                result = comfy.link_template_models(root)
            dest = root / "models" / "text_encoders" / src.name
            self.assertTrue(dest.is_file())
            self.assertFalse(src.exists())
            self.assertEqual(dest.stat().st_size, len(payload))
            gemma = next(p for p in result["placed"] if p["name"] == src.name)
            self.assertEqual(gemma["action"], "moved")
            self.assertEqual(len(result["missing"]), 2)

    def test_link_template_models_drops_downloads_hardlink(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            downloads = home / "Downloads"
            root = Path(tmp) / "ComfyUI"
            dest_dir = root / "models" / "text_encoders"
            downloads.mkdir(parents=True)
            dest_dir.mkdir(parents=True)
            name = "gemma4_e2b_it_int8_convrot.safetensors"
            src = downloads / name
            dest = dest_dir / name
            src.write_bytes(b"x" * 2_000_000)
            os.link(src, dest)
            with patch.object(comfy, "install_root", return_value=root), patch.object(Path, "home", return_value=home):
                result = comfy.link_template_models(root)
            self.assertTrue(dest.is_file())
            self.assertFalse(src.exists())
            gemma = next(p for p in result["placed"] if p["name"] == name)
            self.assertEqual(gemma["action"], "moved")

    def test_flatten_graph_params_skips_wires_and_long_text(self) -> None:
        graph = _graph()
        graph["1"]["inputs"]["text"] = "a red hatchback"
        graph["5"]["inputs"]["steps"] = 8
        graph["5"]["inputs"]["cfg"] = 1.0
        graph["5"]["inputs"]["model"] = ["3", 0]
        graph["5"]["inputs"]["ckpt_name"] = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
        params = comfy.flatten_graph_params(graph)
        self.assertEqual(params["CLIPTextEncode_text"], "a red hatchback")
        self.assertEqual(params["KSampler_steps"], 8)
        self.assertEqual(params["KSampler_cfg"], 1.0)
        self.assertEqual(params["KSampler_seed"], 1)
        self.assertIn("KSampler_ckpt_name", params)
        self.assertNotIn("KSampler_model", params)
        self.assertNotIn("KSampler_filename_prefix", params)

    def test_execution_trace_uses_message_timestamps(self) -> None:
        entry = {
            "status": {
                "status_str": "success",
                "completed": True,
                "messages": [
                    ["execution_start", {"timestamp": 1000.0}],
                    ["executing", {"node": "10", "timestamp": 1000.5}],
                    ["executing", {"node": "20", "timestamp": 1002.5}],
                    ["execution_success", {"timestamp": 1005.0}],
                ],
            }
        }
        trace = comfy.execution_trace(entry)
        self.assertEqual(trace["duration_s"], 5.0)
        self.assertEqual(trace["node_count"], 2)
        by_node = {row["node"]: row["duration_s"] for row in trace["nodes"]}
        self.assertEqual(by_node["10"], 2.0)
        self.assertEqual(by_node["20"], 2.5)

    def test_list_finished_jobs_skips_lab_prefix_and_needs_video(self) -> None:
        graph = _graph()
        graph["5"]["inputs"]["filename_prefix"] = "ComfyUI"
        lab_graph = _graph()
        lab_graph["5"]["inputs"]["filename_prefix"] = "ltx-lab/20260921-test"
        blob = {
            "aaa": {
                "prompt": [1, "aaa", graph, {}, []],
                "outputs": {
                    "9": {"gifs": [{"filename": "clip.mp4", "subfolder": "", "type": "output"}]}
                },
                "status": {
                    "status_str": "success",
                    "completed": True,
                    "messages": [
                        ["execution_start", {"timestamp": 100.0}],
                        ["execution_success", {"timestamp": 110.0}],
                    ],
                },
            },
            "bbb": {
                "prompt": [2, "bbb", lab_graph, {}, []],
                "outputs": {
                    "9": {"gifs": [{"filename": "lab.mp4", "subfolder": "", "type": "output"}]}
                },
                "status": {"status_str": "success", "completed": True, "messages": []},
            },
            "ccc": {
                "prompt": [3, "ccc", graph, {}, []],
                "outputs": {"9": {"images": [{"filename": "still.png", "type": "output"}]}},
                "status": {"status_str": "success", "completed": True, "messages": []},
            },
        }
        jobs = comfy.list_finished_jobs(history_blob=blob)
        by_id = {job["prompt_id"]: job for job in jobs}
        self.assertIn("aaa", by_id)
        self.assertIn("bbb", by_id)
        self.assertNotIn("ccc", by_id)
        self.assertFalse(by_id["aaa"]["lab_owned"])
        self.assertTrue(by_id["bbb"]["lab_owned"])
        self.assertEqual(by_id["aaa"]["trace"]["duration_s"], 10.0)


class ObserveCompareTests(unittest.TestCase):
    def test_compare_observe_packs_flags_faster_and_param_diff(self) -> None:
        from lab.runtime import compare_observe_packs

        left = {
            "identity": {"run_id": "run-a"},
            "job": {
                "engine": "comfyui",
                "duration_s": 120,
                "size_bytes": 10,
                "seed": 1,
                "prompt": "same",
                "workflow": "ltx",
            },
            "params": {"KSampler_steps": 8, "KSampler_cfg": 1.0},
        }
        right = {
            "identity": {"run_id": "run-b"},
            "job": {
                "engine": "comfyui",
                "duration_s": 90,
                "size_bytes": 10,
                "seed": 1,
                "prompt": "same",
                "workflow": "ltx",
            },
            "params": {"KSampler_steps": 4, "KSampler_cfg": 1.0},
        }
        pack = compare_observe_packs(left, right)
        self.assertEqual(pack["faster"], "right")
        changed = {row["key"]: row for row in pack["params_changed"]}
        self.assertEqual(changed["KSampler_steps"]["left"], 8)
        self.assertEqual(changed["KSampler_steps"]["right"], 4)
        self.assertNotIn("KSampler_cfg", changed)


if __name__ == "__main__":
    unittest.main()
