"""Standalone oMLX client for prompt rewrite + KV-cache evidence.

oMLX is a local OpenAI-compatible LLM server (default 127.0.0.1:8000). This lab
never starts it as a child of video generation and never binds port 8000.
Video still runs through LTX-2. oMLX only rewrites the prompt; its hot/SSD
prefix cache helps when the same system instruction is reused.

Configure the backend model and cache in the oMLX admin UI. The lab reads the
loaded default, SSD directory, and hot-cache cap from that server and writes
them onto the next generation as `omlx.json`.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

DEFAULT_URL = "http://127.0.0.1:8000"
SETTINGS_PATH = Path.home() / ".omlx" / "settings.json"
_SECRET_KEYS = {
    "api_key",
    "password",
    "secret_key",
    "hf_token",
    "access_token",
    "sub_keys",
    "authorization",
}
_COOKIE: dict[str, Any] = {"value": "", "ts": 0.0}

# oMLX paged cache is 256-token blocks. A short system prompt never shows
# cached_tokens even on a hit. Keep this prefix stable across requests.
REWRITE_SYSTEM = (
    "You rewrite the user's text into one cinematic video prompt for LTX-2 distilled. "
    "Keep the same subject, action, and setting. Prefer concrete camera, lighting, "
    "weather, and motion words. Output only the rewritten prompt: no quotes, no "
    "preamble, no bullet lists, no camera-script formatting.\n"
    "House style: 24fps, shallow depth of field, natural grain, practical lights, "
    "grounded physics, no logos, no readable signage.\n"
    + (
        "When in doubt, describe visible motion in the first sentence and lighting in the second. "
        * 12
    )
)


class OmlxError(Exception):
    """oMLX call failed."""


def base_url() -> str:
    return (os.environ.get("OMLX_BASE_URL") or DEFAULT_URL).rstrip("/")


def api_key() -> str:
    env = (os.environ.get("OMLX_API_KEY") or "").strip()
    if env:
        return env
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        return str((data.get("auth") or {}).get("api_key") or "").strip()
    except (OSError, json.JSONDecodeError, TypeError):
        return ""


def _settings() -> dict[str, Any]:
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def drop_secrets(obj: Any) -> Any:
    """Strip credentials before anything is returned to the browser or ledger."""
    if isinstance(obj, dict):
        return {
            key: drop_secrets(value)
            for key, value in obj.items()
            if str(key).lower() not in _SECRET_KEYS
        }
    if isinstance(obj, list):
        return [drop_secrets(item) for item in obj]
    return obj


def _request(
    path: str,
    *,
    method: str = "GET",
    body: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 30,
    raw: bool = False,
) -> tuple[int, dict[str, str], bytes]:
    url = base_url() + path
    hdrs = {"Accept": "application/json"}
    key = api_key()
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        hdrs["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k: v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        if raw:
            return exc.code, {k: v for k, v in exc.headers.items()}, payload
        detail = payload.decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
            message = (parsed.get("error") or {}).get("message") or parsed.get("detail") or detail
        except json.JSONDecodeError:
            message = detail or str(exc)
        raise OmlxError(f"oMLX HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise OmlxError(f"oMLX is not reachable at {base_url()} ({exc.reason})") from exc


def _json(path: str, **kwargs) -> tuple[int, dict[str, str], Any]:
    code, headers, raw = _request(path, raw=True, **kwargs)
    try:
        parsed = json.loads(raw.decode("utf-8") or "null")
    except json.JSONDecodeError:
        parsed = None
    return code, headers, parsed


def _cache_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    cache_cfg = settings.get("cache") or {}
    model_cfg = settings.get("model") or {}
    ssd_dir = str(cache_cfg.get("ssd_cache_dir") or Path.home() / ".omlx" / "cache")
    models_dir = str(model_cfg.get("model_dir") or Path.home() / ".omlx" / "models")
    return {
        "enabled": bool(cache_cfg.get("enabled", True)),
        "ssd_dir": ssd_dir,
        "ssd_max": cache_cfg.get("ssd_cache_max_size"),
        "hot_cache_only": bool(cache_cfg.get("hot_cache_only", False)),
        "hot_cache_max_size": cache_cfg.get("hot_cache_max_size"),
        "initial_cache_blocks": cache_cfg.get("initial_cache_blocks"),
        "models_dir": models_dir,
        "base_path": str(Path.home() / ".omlx"),
        "settings_path": str(SETTINGS_PATH),
        "response_state_dir": str(Path(ssd_dir) / "response-state"),
    }


def _catalog_from_admin(body: Any) -> list[dict[str, Any]]:
    models = body
    if isinstance(body, dict):
        models = body.get("models") or []
    catalog = []
    for item in models or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        catalog.append({
            "id": str(item["id"]),
            "loaded": bool(item.get("loaded")),
            "is_default": bool(item.get("is_default")),
            "pinned": bool(item.get("pinned")),
            "path": item.get("model_path") or None,
            "size": item.get("actual_size_formatted") or item.get("estimated_size_formatted"),
        })
    return catalog


def _runtime_from_stats(stats: dict[str, Any], model: Optional[str]) -> dict[str, Any]:
    stats = drop_secrets(stats or {})
    runtime_cache = stats.get("runtime_cache") or {}
    models = runtime_cache.get("models") or []
    chosen = None
    if model:
        chosen = next((row for row in models if row.get("id") == model), None)
    if chosen is None and models:
        chosen = models[0]
    compact = []
    for row in models:
        compact.append({
            "id": row.get("id"),
            "block_size": row.get("block_size"),
            "indexed_blocks": row.get("indexed_blocks"),
            "num_files": row.get("num_files"),
            "total_size_bytes": row.get("total_size_bytes"),
            "hot_cache_size_bytes": row.get("hot_cache_size_bytes"),
            "hot_cache_max_bytes": row.get("hot_cache_max_bytes"),
            "hot_cache_entries": row.get("hot_cache_entries"),
            "hits": row.get("hits"),
            "misses": row.get("misses"),
            "saves": row.get("saves"),
            "loads": row.get("loads"),
        })
    return {
        "total_cached_tokens": stats.get("total_cached_tokens"),
        "cache_efficiency": stats.get("cache_efficiency"),
        "total_requests": stats.get("total_requests"),
        "base_path": runtime_cache.get("base_path"),
        "ssd_dir": runtime_cache.get("ssd_cache_dir"),
        "response_state_dir": runtime_cache.get("response_state_dir"),
        "model": chosen,
        "models": compact,
    }


def _how(url: str, models_dir: str) -> dict[str, str]:
    return {
        "install": "brew tap jundot/omlx https://github.com/jundot/omlx && brew install jundot/omlx/omlx",
        "start": "omlx start",
        "app": "Open /Applications/oMLX.app",
        "admin": f"{url}/admin",
        "chat": f"{url}/admin/chat",
        "models_dir": models_dir,
        "key": "Set OMLX_API_KEY, or leave ~/.omlx/settings.json in place (the lab reads auth.api_key locally and never returns it).",
        "role": "Load the model and set SSD/hot cache in the oMLX admin. The lab rewrites prompts with that backend; LTX-2 still generates the mp4.",
        "configure": (
            "In oMLX admin: load one model and set it as default, then set Cache → SSD directory "
            "and hot-cache size. Apply, then return here. The lab uses that default unless you pick another loaded model."
        ),
    }


def status() -> dict[str, Any]:
    url = base_url()
    settings = _settings()
    cache = _cache_from_settings(settings)
    how = _how(url, cache["models_dir"])
    result: dict[str, Any] = {
        "ready": False,
        "url": url,
        "default_model": None,
        "models": [],
        "catalog": [],
        "loaded": [],
        "cache": cache,
        "auth_configured": bool(api_key()),
        "how": how,
        "error": None,
    }
    try:
        code, _, health = _json("/health", timeout=1.2)
    except OmlxError as exc:
        result["error"] = str(exc)
        result["how"]["start"] = "omlx start   # or open oMLX from Applications"
        return result
    if code != 200 or not isinstance(health, dict):
        result["error"] = f"oMLX /health returned HTTP {code}"
        return result
    result["default_model"] = health.get("default_model")
    pool = health.get("engine_pool") or {}
    result["loaded_count"] = pool.get("loaded_count")
    result["model_count"] = pool.get("model_count")

    try:
        code, _, models = _json("/v1/models", timeout=2)
    except OmlxError as exc:
        result["error"] = str(exc)
        return result
    if code == 401:
        result["error"] = "oMLX requires an API key. Set OMLX_API_KEY or use the key in ~/.omlx/settings.json."
        return result
    if code != 200:
        result["error"] = f"oMLX /v1/models returned HTTP {code}"
        return result
    data = (models or {}).get("data") if isinstance(models, dict) else []
    ids = [str(item.get("id")) for item in data or [] if item.get("id")]
    result["models"] = ids
    result["loaded"] = [mid for mid in ids if mid == result["default_model"] or (result["default_model"] or "").endswith(mid)]
    result["ready"] = bool(ids)
    if not ids:
        result["error"] = f"oMLX is up but has no models in {how['models_dir']}. Download one from {how['admin']}."
        return result
    try:
        extra = _admin_headers()
        code, _, admin_models = _json("/admin/api/models", headers=extra, timeout=3)
        if code == 200:
            catalog = _catalog_from_admin(admin_models)
            result["catalog"] = catalog
            result["loaded"] = [row["id"] for row in catalog if row.get("loaded")]
            default = next((row["id"] for row in catalog if row.get("is_default")), result["default_model"])
            if default:
                result["default_model"] = default
        code, _, settings_live = _json("/admin/api/global-settings", headers=extra, timeout=3)
        if code == 200 and isinstance(settings_live, dict):
            live_cache = _cache_from_settings(drop_secrets(settings_live))
            result["cache"].update({k: v for k, v in live_cache.items() if v not in (None, "")})
    except OmlxError:
        pass
    return result


def _admin_cookie() -> str:
    code, headers, _ = _json("/admin/api/login", method="POST", body={"api_key": api_key(), "remember": False}, timeout=5)
    if code != 200:
        raise OmlxError("oMLX admin login failed")
    cookie = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
    return cookie.split(";", 1)[0]


def _admin_headers() -> dict[str, str]:
    now = time.time()
    cookie = str(_COOKIE.get("value") or "")
    if cookie and now - float(_COOKIE.get("ts") or 0) < 50:
        return {"Cookie": cookie}
    cookie = _admin_cookie()
    _COOKIE["value"] = cookie
    _COOKIE["ts"] = now
    return {"Cookie": cookie} if cookie else {}


def clear_cache() -> dict[str, Any]:
    extra = _admin_headers()
    hot_code, _, hot = _json("/admin/api/hot-cache/clear", method="POST", body={}, headers=extra, timeout=10)
    ssd_code, _, ssd = _json("/admin/api/ssd-cache/clear", method="POST", body={}, headers=extra, timeout=30)
    _COOKIE["value"] = ""
    return {
        "hot": hot if hot_code == 200 else {"error": f"HTTP {hot_code}"},
        "ssd": ssd if ssd_code == 200 else {"error": f"HTTP {ssd_code}"},
    }


def probe(model: str, prompt: str) -> dict[str, Any]:
    extra = _admin_headers()
    code, _, body = _json(
        "/admin/api/cache/probe",
        method="POST",
        headers=extra,
        timeout=20,
        body={
            "model_id": model,
            "messages": [
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        },
    )
    if code != 200 or not isinstance(body, dict):
        raise OmlxError(f"oMLX cache probe HTTP {code}")
    return {
        "model_id": body.get("model_id") or model,
        "model_loaded": bool(body.get("model_loaded")),
        "reason": body.get("reason"),
        "total_tokens": body.get("total_tokens"),
        "block_size": body.get("block_size"),
        "total_blocks": body.get("total_blocks"),
        "blocks_hot": body.get("blocks_ssd_hot"),
        "blocks_ssd": body.get("blocks_ssd_disk"),
        "blocks_cold": body.get("blocks_cold"),
        "ssd_hit_tokens": body.get("ssd_hit_tokens"),
        "cold_tokens": body.get("cold_tokens"),
    }


def snapshot(*, model: Optional[str] = None, prompt: Optional[str] = None, do_probe: bool = False) -> dict[str, Any]:
    info = status()
    chosen = model or info.get("default_model") or (info.get("models") or [None])[0]
    snap: dict[str, Any] = {
        "url": info.get("url"),
        "admin": (info.get("how") or {}).get("admin"),
        "model": chosen,
        "default_model": info.get("default_model"),
        "models_dir": (info.get("cache") or {}).get("models_dir"),
        "cache": dict(info.get("cache") or {}),
        "catalog": info.get("catalog") or [],
        "loaded": info.get("loaded") or [],
        "runtime": None,
        "probe": None,
        "error": info.get("error"),
    }
    if not info.get("ready"):
        return snap
    try:
        extra = _admin_headers()
        code, _, stats = _json("/admin/api/stats", headers=extra, timeout=5)
        if code == 200 and isinstance(stats, dict):
            runtime = _runtime_from_stats(stats, chosen)
            snap["runtime"] = runtime
            if runtime.get("ssd_dir"):
                snap["cache"]["ssd_dir"] = runtime["ssd_dir"]
            if runtime.get("base_path"):
                snap["cache"]["base_path"] = runtime["base_path"]
            if runtime.get("response_state_dir"):
                snap["cache"]["response_state_dir"] = runtime["response_state_dir"]
        if do_probe and chosen and prompt:
            snap["probe"] = probe(chosen, prompt)
    except OmlxError as exc:
        snap["error"] = str(exc)
    return drop_secrets(snap)


def rewrite(prompt: str, model: Optional[str] = None, max_tokens: int = 120) -> dict[str, Any]:
    text = (prompt or "").strip()
    if not text:
        raise OmlxError("prompt is empty")
    info = status()
    if not info.get("ready"):
        raise OmlxError(info.get("error") or "oMLX is not ready")
    chosen = model or info.get("default_model") or (info.get("models") or [None])[0]
    if not chosen:
        raise OmlxError("oMLX has no model loaded")
    payload = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": text},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    # Streaming is required: non-stream responses report cached_tokens=0 even on hits.
    code, headers, raw = _request("/v1/chat/completions", method="POST", body=payload, timeout=90, raw=True)
    if code >= 400:
        raise OmlxError(f"oMLX HTTP {code}: {raw.decode('utf-8', 'replace')[:400]}")
    content = ""
    usage: dict[str, Any] = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        event = json.loads(data)
        if event.get("usage"):
            usage = event["usage"]
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content") or ""
            content += piece
            if not piece:
                message = choice.get("message") or {}
                content += message.get("content") or ""
    rewritten = content.strip() or text
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens")
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    result: dict[str, Any] = {
        "prompt": rewritten,
        "source_prompt": text,
        "model": chosen,
        "url": base_url(),
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "cached_tokens": None if cached is None else int(cached),
            "ttft_ms": round(float(usage.get("time_to_first_token") or 0) * 1000, 1) if usage.get("time_to_first_token") is not None else None,
            "total_ms": round(float(usage.get("total_time") or 0) * 1000, 1) if usage.get("total_time") is not None else None,
        },
        "cache_hit": bool(cached and int(cached) > 0),
        "cache": dict(info.get("cache") or {}),
        "probe": None,
        "snapshot": None,
    }
    try:
        snap = snapshot(model=chosen, prompt=text, do_probe=True)
        result["snapshot"] = snap
        result["probe"] = snap.get("probe")
        if snap.get("cache"):
            result["cache"] = snap["cache"]
    except OmlxError as exc:
        result["snapshot_error"] = str(exc)
    return drop_secrets(result)
