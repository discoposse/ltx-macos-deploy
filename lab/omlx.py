"""Standalone oMLX client for prompt rewrite + KV-cache evidence.

oMLX is a local OpenAI-compatible LLM server (default 127.0.0.1:8000). This lab
never starts it as a child of video generation and never binds port 8000.
Video still runs through LTX-2. oMLX only rewrites the prompt; its hot/SSD
prefix cache helps when the same system instruction is reused.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

DEFAULT_URL = "http://127.0.0.1:8000"
SETTINGS_PATH = Path.home() / ".omlx" / "settings.json"

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


def status() -> dict[str, Any]:
    url = base_url()
    settings = _settings()
    cache_cfg = settings.get("cache") or {}
    ssd_dir = str(cache_cfg.get("ssd_cache_dir") or Path.home() / ".omlx" / "cache")
    how = {
        "install": "brew tap jundot/omlx https://github.com/jundot/omlx && brew install jundot/omlx/omlx",
        "start": "omlx start",
        "app": "Open /Applications/oMLX.app",
        "admin": f"{url}/admin",
        "chat": f"{url}/admin/chat",
        "models_dir": str((settings.get("model") or {}).get("model_dir") or Path.home() / ".omlx" / "models"),
        "key": "Set OMLX_API_KEY, or leave ~/.omlx/settings.json in place (the lab reads auth.api_key locally and never returns it).",
        "role": "oMLX rewrites prompts. LTX-2 still generates the mp4.",
    }
    result: dict[str, Any] = {
        "ready": False,
        "url": url,
        "default_model": None,
        "models": [],
        "loaded": [],
        "cache": {
            "enabled": bool(cache_cfg.get("enabled", True)),
            "ssd_dir": ssd_dir,
            "hot_cache_only": bool(cache_cfg.get("hot_cache_only", False)),
        },
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


def _admin_cookie() -> str:
    code, headers, _ = _json("/admin/api/login", method="POST", body={"api_key": api_key(), "remember": False}, timeout=5)
    if code != 200:
        raise OmlxError("oMLX admin login failed")
    cookie = headers.get("Set-Cookie") or headers.get("set-cookie") or ""
    return cookie.split(";", 1)[0]


def clear_cache() -> dict[str, Any]:
    cookie = _admin_cookie()
    extra = {"Cookie": cookie} if cookie else {}
    hot_code, _, hot = _json("/admin/api/hot-cache/clear", method="POST", body={}, headers=extra, timeout=10)
    ssd_code, _, ssd = _json("/admin/api/ssd-cache/clear", method="POST", body={}, headers=extra, timeout=30)
    return {
        "hot": hot if hot_code == 200 else {"error": f"HTTP {hot_code}"},
        "ssd": ssd if ssd_code == 200 else {"error": f"HTTP {ssd_code}"},
    }


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
    return {
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
    }
