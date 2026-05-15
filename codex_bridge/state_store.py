from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .models import PendingCardAction, WatchedSession

logger = logging.getLogger(__name__)


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data = {
            "watched_sessions": {},
            "session_aliases": {},
            "processed_event_keys": {},
            "pending_actions": {},
        }
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            self._data = json.load(f)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def list_watched(self) -> List[WatchedSession]:
        with self._lock:
            result: List[WatchedSession] = []
            for v in self._data["watched_sessions"].values():
                raw = dict(v)
                raw.setdefault("session_alias", "")
                raw.setdefault("header_template", "blue")
                result.append(WatchedSession(**raw))
            return result

    def set_alias(self, alias: str, session_id: str) -> None:
        alias_key = alias.strip().lower()
        if not alias_key:
            return
        with self._lock:
            self._data["session_aliases"][alias_key] = session_id.strip()
            self._save()

    def remove_alias(self, alias: str) -> bool:
        alias_key = alias.strip().lower()
        with self._lock:
            removed = self._data["session_aliases"].pop(alias_key, None) is not None
            if removed:
                self._save()
            return removed

    def list_aliases(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._data["session_aliases"])

    def resolve_session_ref(self, value: str) -> str:
        raw = value.strip()
        if not raw:
            return ""
        if raw.startswith("@"):
            raw = raw[1:]
        alias_key = raw.lower()
        with self._lock:
            return str(self._data["session_aliases"].get(alias_key, value.strip()))

    def set_watch(self, watched: WatchedSession) -> None:
        with self._lock:
            self._data["watched_sessions"][watched.session_id] = asdict(watched)
            self._save()

    def remove_watch(self, session_id: str) -> bool:
        with self._lock:
            removed = self._data["watched_sessions"].pop(session_id, None) is not None
            if removed:
                self._save()
            return removed

    def get_watch(self, session_id: str) -> Optional[WatchedSession]:
        with self._lock:
            data = self._data["watched_sessions"].get(session_id)
            if not data:
                return None
            raw = dict(data)
            raw.setdefault("session_alias", "")
            raw.setdefault("header_template", "blue")
            return WatchedSession(**raw)

    def mark_processed(self, event_key: str) -> None:
        with self._lock:
            self._data["processed_event_keys"][event_key] = True
            self._save()

    def is_processed(self, event_key: str) -> bool:
        with self._lock:
            return bool(self._data["processed_event_keys"].get(event_key))

    def put_action(self, action: PendingCardAction) -> None:
        with self._lock:
            self._data["pending_actions"][action.action_id] = asdict(action)
            self._save()

    def get_action(self, action_id: str) -> Optional[PendingCardAction]:
        with self._lock:
            data = self._data["pending_actions"].get(action_id)
            return PendingCardAction(**data) if data else None

    def update_action_status(self, action_id: str, status: str) -> None:
        with self._lock:
            action = self._data["pending_actions"].get(action_id)
            if not action:
                return
            action["status"] = status
            self._save()

    def find_pending_action(self, action_type: str, session_id: str, key: str, value: Any) -> Optional[PendingCardAction]:
        with self._lock:
            for raw in self._data["pending_actions"].values():
                if raw.get("action_type") != action_type:
                    continue
                if raw.get("session_id") != session_id:
                    continue
                if raw.get("status") != "pending":
                    continue

                payload_text = raw.get("payload_json", "{}")
                try:
                    payload = json.loads(payload_text)
                except Exception:
                    logger.exception("failed to parse pending action payload_json: action_id=%s", raw.get("action_id"))
                    continue
                if payload.get(key) == value:
                    return PendingCardAction(**raw)
            return None
