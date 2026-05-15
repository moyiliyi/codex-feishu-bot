from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Callable

from codex_bridge.models import PendingCardAction
from codex_bridge.state_store import StateStore

from .client import AppServerClient
from .events import TurnCompleted

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ContinueCardRequest:
    action_id: str
    thread_id: str
    turn_id: str
    last_message: str


class TurnRouter:
    def __init__(
        self,
        state: StateStore,
        client: AppServerClient,
        send_card: Callable[[ContinueCardRequest], None],
    ) -> None:
        self.state = state
        self.client = client
        self.send_card = send_card

    def on_turn_completed(self, event: TurnCompleted) -> str:
        logger.info("turn_router.on_turn_completed thread=%s turn=%s", event.thread_id, event.turn_id)
        existing = self.state.find_pending_action(
            action_type="appserver_continue",
            session_id=event.thread_id,
            key="turn_id",
            value=event.turn_id,
        )
        if existing:
            logger.info("turn_router dedup hit action_id=%s", existing.action_id)
            return existing.action_id

        action_id = str(uuid.uuid4())
        payload = {
            "thread_id": event.thread_id,
            "turn_id": event.turn_id,
        }
        self.state.put_action(
            PendingCardAction(
                action_id=action_id,
                session_id=event.thread_id,
                action_type="appserver_continue",
                payload_json=json.dumps(payload, ensure_ascii=False),
                status="pending",
            )
        )
        self.send_card(
            ContinueCardRequest(
                action_id=action_id,
                thread_id=event.thread_id,
                turn_id=event.turn_id,
                last_message=event.last_assistant_message,
            )
        )
        logger.info("turn_router created action_id=%s", action_id)
        return action_id

    def continue_with_prompt(self, action_id: str, prompt: str) -> bool:
        record = self.state.get_action(action_id)
        if not record or record.action_type != "appserver_continue":
            return False
        if record.status != "pending":
            return False

        prompt_text = prompt.strip()
        if not prompt_text:
            return False

        payload = json.loads(record.payload_json)
        thread_id = str(payload.get("thread_id", ""))
        if not thread_id:
            self.state.update_action_status(action_id, "invalid")
            return False

        self.client.turn_start(thread_id=thread_id, user_input=prompt_text)
        self.state.update_action_status(action_id, "done")
        return True
