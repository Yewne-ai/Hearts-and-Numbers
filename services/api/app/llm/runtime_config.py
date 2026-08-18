"""Runtime-editable LLM config (personas + sampling params).

Effective config = built-in defaults overlaid with whatever is stored in the
overrides JSON file (written by the admin API). The file is re-read on demand
with an mtime check, so admin edits take effect immediately with no process
restart. Defaults always remain the safe fallback.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.llm.defaults import DEFAULT_PARAMS, DEFAULT_PERSONAS, PERSONA_KEYS

_OVERRIDES_PATH = Path(__file__).parent / "runtime_overrides.json"

_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None


def _default_params() -> dict:
    params = dict(DEFAULT_PARAMS)
    params["model"] = settings.deepseek_model
    return params


def _load_overrides() -> dict:
    if not _OVERRIDES_PATH.exists():
        return {}
    try:
        return json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def get_config(force: bool = False) -> dict:
    """Return effective {"personas": {...}, "params": {...}} merged over defaults."""
    global _cache, _cache_mtime
    mtime = _OVERRIDES_PATH.stat().st_mtime if _OVERRIDES_PATH.exists() else 0.0
    if not force and _cache is not None and _cache_mtime == mtime:
        return _cache

    overrides = _load_overrides()
    personas = dict(DEFAULT_PERSONAS)
    for key, value in (overrides.get("personas") or {}).items():
        if key in PERSONA_KEYS and isinstance(value, str) and value.strip():
            personas[key] = value

    params = _default_params()
    for key, value in (overrides.get("params") or {}).items():
        if key in params and value is not None:
            params[key] = value

    _cache = {"personas": personas, "params": params}
    _cache_mtime = mtime
    return _cache


def get_persona(persona: str) -> str:
    personas = get_config()["personas"]
    return personas.get(persona, personas["nini"])


def get_params() -> dict:
    return dict(get_config()["params"])


def get_defaults() -> dict:
    return {"personas": dict(DEFAULT_PERSONAS), "params": _default_params()}


def save_overrides(personas: dict, params: dict) -> dict:
    """Atomically persist overrides; keep a timestamped backup of the prior file."""
    payload = {
        "personas": personas,
        "params": params,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if _OVERRIDES_PATH.exists():
        backup = _OVERRIDES_PATH.with_name(
            f"runtime_overrides.bak.{time.strftime('%Y%m%d%H%M%S')}.json"
        )
        try:
            backup.write_text(
                _OVERRIDES_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
        except OSError:
            pass

    fd, tmp = tempfile.mkstemp(dir=str(_OVERRIDES_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _OVERRIDES_PATH)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    return get_config(force=True)


def reset_overrides() -> dict:
    """Revert to built-in defaults (archives the current overrides file)."""
    if _OVERRIDES_PATH.exists():
        backup = _OVERRIDES_PATH.with_name(
            f"runtime_overrides.bak.{time.strftime('%Y%m%d%H%M%S')}.json"
        )
        try:
            os.replace(_OVERRIDES_PATH, backup)
        except OSError:
            try:
                _OVERRIDES_PATH.unlink()
            except OSError:
                pass
    return get_config(force=True)


# [2026-08-11] 单一人格。客户端传什么都用 yewne——保留旧值只是为了不让老客户端
# 吃 422，不是还支持多人格。任何需要"按人格取东西"的地方都该先过这个函数，
# 否则会静默退回到某个旧人格（TTS 音色、Aftercare 文案都有 .get 兜底，
# 拿不到 yewne 就悄悄用妮妮那套，界面上看不出来）。
def resolve_persona(persona: str | None) -> str:
    """把客户端传来的人格值解析成实际使用的那个。"""
    return "yewne"
