from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, Set

from .models import ApprovalEvent, TurnCompleteEvent
from .session_parser import parse_session_line
from .session_registry import discover_sessions
from .state_store import StateStore


class CodexWatcher:
    def __init__(
        self,
        codex_home: str,
        state_store: StateStore,
        on_approval: Callable[[ApprovalEvent], None],
        on_complete: Callable[[TurnCompleteEvent], None],
        get_listen_session_ids: Callable[[], Set[str]] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self.codex_home = codex_home
        self.state_store = state_store
        self.on_approval = on_approval
        self.on_complete = on_complete
        self.get_listen_session_ids = get_listen_session_ids
        self.poll_interval = poll_interval
        self._offsets: Dict[str, int] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            configured_session_ids: Set[str] = set()
            if self.get_listen_session_ids is not None:
                configured_session_ids = set(self.get_listen_session_ids() or set())

            # Empty configured session ids means "listen to nothing".
            if not configured_session_ids:
                time.sleep(self.poll_interval)
                continue

            sessions = discover_sessions(self.codex_home)
            for watch in self.state_store.list_watched():
                if watch.session_id not in configured_session_ids:
                    continue
                path = sessions.get(watch.session_id)
                if not path or not os.path.exists(path):
                    continue
                self._process_file(path, watch.session_id)
            time.sleep(self.poll_interval)

    def _process_file(self, path: str, session_id: str) -> None:
        offset = self._offsets.get(path, 0)
        with open(path, "r", encoding="utf-8") as f:
            f.seek(offset)
            for line in f:
                event = parse_session_line(line, session_id)
                if event is None:
                    continue
                if self.state_store.is_processed(event.event_key):
                    continue
                if isinstance(event, ApprovalEvent):
                    self.on_approval(event)
                elif isinstance(event, TurnCompleteEvent):
                    self.on_complete(event)
                self.state_store.mark_processed(event.event_key)
            self._offsets[path] = f.tell()
