from __future__ import annotations

import os
import json
from typing import Dict, Set


class Config:
    APP_ID = os.getenv("APP_ID", "")
    APP_SECRET = os.getenv("APP_SECRET", "")
    CODEX_HOME = os.getenv("CODEX_HOME", os.path.expanduser("~/.codex"))
    STATE_PATH = os.getenv("STATE_PATH", "./runtime/state.json")
    LISTEN_SESSION_ID_PATH = os.getenv(
        "LISTEN_SESSION_ID_PATH",
         "./runtime/listen_session_id.json"
    )
    BOT_ADMIN_OPEN_ID = os.getenv("BOT_ADMIN_OPEN_ID", "")
    APP_SERVER_WS_URL = os.getenv("APP_SERVER_WS_URL", "ws://127.0.0.1:8787")


def validate_config() -> None:
    missing = []
    if not Config.APP_ID:
        missing.append("APP_ID")
    if not Config.APP_SECRET:
        missing.append("APP_SECRET")
    if missing:
        raise RuntimeError("Missing required env vars: " + ", ".join(missing))


def load_listen_session_id(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def load_listen_session_ids(path: str) -> Set[str]:
    return set(load_listen_session_map(path).values())


def load_listen_session_map(path: str) -> Dict[str, str]:
    text = load_listen_session_id(path)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}

    # Accept either:
    # 1) {"sessions": {"prod":"session-id"}}
    # 2) {"prod":"session-id"}
    raw_map = data.get("sessions") if isinstance(data, dict) and isinstance(data.get("sessions"), dict) else data
    if not isinstance(raw_map, dict):
        return {}

    result: Dict[str, str] = {}
    for alias, session_id in raw_map.items():
        alias_text = str(alias).strip()
        session_text = str(session_id).strip()
        if alias_text and session_text:
            result[alias_text] = session_text
    return result


def resolve_session_ref(path: str, ref: str) -> str:
    key = ref.strip()
    if not key:
        return ""
    return load_listen_session_map(path).get(key, "")
