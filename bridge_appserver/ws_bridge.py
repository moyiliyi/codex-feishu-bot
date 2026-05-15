from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from typing import Callable, Set

import websockets

from .client import AppServerClient, Transport
from .events import ApprovalRequest, TurnCompleted, parse_appserver_event

logger = logging.getLogger(__name__)


class WsTransport(Transport):
    def __init__(self) -> None:
        self._outgoing: queue.Queue[dict] = queue.Queue()

    def send(self, payload: dict) -> None:
        self._outgoing.put(payload)

    def pop_nowait(self) -> dict | None:
        try:
            return self._outgoing.get_nowait()
        except queue.Empty:
            return None


class AppServerWsBridge:
    def __init__(
        self,
        ws_url: str,
        client: AppServerClient,
        transport: WsTransport,
        get_listen_session_ids: Callable[[], Set[str]],
        on_approval: Callable[[ApprovalRequest], None],
        on_turn_completed: Callable[[TurnCompleted], None],
    ) -> None:
        self.ws_url = ws_url
        self.client = client
        self.transport = transport
        self.get_listen_session_ids = get_listen_session_ids
        self.on_approval = on_approval
        self.on_turn_completed = on_turn_completed
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._resume_requests: dict[str, str] = {}
        self._attached_sessions: set[str] = set()
        self._turn_text_buffers: dict[tuple[str, str], str] = {}

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
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        while not self._stop.is_set():
            try:
                logger.info("connecting app-server ws: %s", self.ws_url)
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("app-server ws connected")
                    self.client.initialize("feishu-bridge")
                    self.client.initialized()
                    last_subscribe = 0.0
                    while not self._stop.is_set():
                        now = time.time()
                        if now - last_subscribe > 2.0:
                            session_ids = sorted(self.get_listen_session_ids())
                            logger.info("active listen sessions: %s", session_ids)
                            session_set = set(session_ids)
                            # Clear stale attached markers if config changed.
                            self._attached_sessions.intersection_update(session_set)
                            # Attach this connection to each watched thread so turn/item notifications flow here.
                            for session_id in session_ids:
                                if session_id in self._attached_sessions:
                                    continue
                                req_id = self.client.thread_resume(session_id)
                                self._resume_requests[req_id] = session_id
                                logger.info("request thread/resume: threadId=%s id=%s", session_id, req_id)
                            last_subscribe = now

                        while True:
                            payload = self.transport.pop_nowait()
                            if payload is None:
                                break
                            logger.info("ws send: method=%s id=%s", payload.get("method"), payload.get("id"))
                            await ws.send(json.dumps(payload, ensure_ascii=False))

                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                        except asyncio.TimeoutError:
                            continue
                        except websockets.ConnectionClosed:
                            break

                        try:
                            msg = json.loads(raw)
                        except Exception:
                            logger.exception("failed to parse ws message as json: raw=%r", raw)
                            continue
                        if msg.get("method") == "mcpServer/elicitation/request":
                            params_dbg = msg.get("params", {})
                            logger.info(
                                    f"mcp elicitation raw: id={msg.get('id')} params_dbg:{params_dbg}\n\n raw msg:{msg}",
                            )
                        msg_id = msg.get("id")
                        if "method" in msg:
                            logger.info("ws recv method=%s id=%s", msg.get("method"), msg.get("id"))
                            method = str(msg.get("method", ""))
                            if method == "item/agentMessage/delta":
                                params = msg.get("params", {}) if isinstance(msg.get("params"), dict) else {}
                                thread_id = str(params.get("threadId") or params.get("thread_id") or "")
                                turn_id = str(params.get("turnId") or params.get("turn_id") or "")
                                delta = params.get("delta")
                                if thread_id and turn_id and isinstance(delta, str) and delta:
                                    key = (thread_id, turn_id)
                                    self._turn_text_buffers[key] = self._turn_text_buffers.get(key, "") + delta
                        else:
                            logger.info("ws recv response id=%s  method=%s has_result=%s has_error=%s", msg_id, msg.get('method'),"result" in msg, "error" in msg)
                            req_id = str(msg_id) if msg_id is not None else ""
                            session_id = self._resume_requests.pop(req_id, "")
                            if session_id:
                                if "result" in msg and "error" not in msg:
                                    self._attached_sessions.add(session_id)
                                    logger.info("thread/resume attached: threadId=%s id=%s", session_id, req_id)
                                else:
                                    logger.warning(
                                        "thread/resume failed: threadId=%s id=%s error=%s",
                                        session_id,
                                        req_id,
                                        msg.get("error"),
                                    )

                        event = parse_appserver_event(msg)
                        if event is None:
                            continue
                        if isinstance(event, ApprovalRequest):
                            session_ids = self.get_listen_session_ids()
                            event_thread_id = event.thread_id
                            if not event_thread_id and len(session_ids) == 1:
                                event_thread_id = next(iter(session_ids))
                                logger.warning(
                                    "approval event missing thread_id, fallback to only listened thread: %s (method=%s request_id=%r)",
                                    event_thread_id,
                                    event.raw_method,
                                    event.request_id,
                                )
                                event = ApprovalRequest(
                                    request_id=event.request_id,
                                    thread_id=event_thread_id,
                                    turn_id=event.turn_id,
                                    approval_type=event.approval_type,
                                    summary=event.summary,
                                    raw_method=event.raw_method,
                                    options=event.options,
                                )
                            logger.info("approval event: method=%s thread_id=%s turn_id=%s in_listen=%s", event.raw_method, event.thread_id, event.turn_id, event.thread_id in session_ids)
                            if event.thread_id in session_ids:
                                self.on_approval(event)
                            else:
                                logger.warning(
                                    "approval event ignored (not listened): method=%s thread_id=%s listened=%s",
                                    event.raw_method,
                                    event.thread_id,
                                    sorted(session_ids),
                                )
                        elif isinstance(event, TurnCompleted):
                            session_ids = self.get_listen_session_ids()
                            logger.info("turn completed event: thread_id=%s turn_id=%s in_listen=%s", event.thread_id, event.turn_id, event.thread_id in session_ids)
                            if event.thread_id in session_ids:
                                key = (event.thread_id, event.turn_id)
                                buf = self._turn_text_buffers.pop(key, "")
                                final_event = event
                                if not final_event.last_assistant_message and buf.strip():
                                    final_event = TurnCompleted(
                                        thread_id=event.thread_id,
                                        turn_id=event.turn_id,
                                        last_assistant_message=buf.strip(),
                                    )
                                self.on_turn_completed(final_event)
            except Exception:
                logger.exception("app-server ws bridge reconnecting after unexpected exception")
                await asyncio.sleep(1.0)
