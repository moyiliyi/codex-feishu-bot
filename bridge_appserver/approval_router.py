from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from codex_bridge.state_store import StateStore
from codex_bridge.models import PendingCardAction

from .client import AppServerClient
from .events import ApprovalRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApprovalCardRequest:
    action_id: str
    thread_id: str
    turn_id: str
    summary: str
    options: list[dict[str, object]]


class ApprovalRouter:
    def __init__(
        self,
        state: StateStore,
        client: AppServerClient,
        send_card: Callable[[ApprovalCardRequest], None],
    ) -> None:
        self.state = state
        self.client = client
        self.send_card = send_card

    def on_approval_request(self, event: ApprovalRequest) -> str:
        logger.info("approval_router.on_approval_request thread=%s turn=%s request_id=%s", event.thread_id, event.turn_id, event.request_id)
        existing = self.state.find_pending_action(
            action_type="appserver_approval",
            session_id=event.thread_id,
            key="request_id",
            value=event.request_id,
        )
        if existing:
            logger.info("approval_router dedup hit action_id=%s", existing.action_id)
            return existing.action_id

        action_id = str(uuid.uuid4())
        payload = {
            "request_id": event.request_id,
            "thread_id": event.thread_id,
            "turn_id": event.turn_id,
            "summary": event.summary,
            "approval_type": event.approval_type,
            "options": event.options,
        }
        self.state.put_action(
            PendingCardAction(
                action_id=action_id,
                session_id=event.thread_id,
                action_type="appserver_approval",
                payload_json=json.dumps(payload, ensure_ascii=False),
                status="pending",
            )
        )
        self.send_card(
            ApprovalCardRequest(
                action_id=action_id,
                thread_id=event.thread_id,
                turn_id=event.turn_id,
                summary=event.summary,
                options=event.options,
            )
        )
        logger.info("approval_router created action_id=%s", action_id)
        return action_id

    def resolve_action(self, action_id: str, decision: object, reason: str = "") -> bool:
        record = self.state.get_action(action_id)
        if not record or record.action_type != "appserver_approval":
            return False
        if record.status != "pending":
            return False

        payload = json.loads(record.payload_json)
        request_id = payload.get("request_id")
        if request_id is None or request_id == "":
            self.state.update_action_status(action_id, "invalid")
            return False
        valid_decisions: list[Any] = []
        for item in payload.get("options", []):
            if not isinstance(item, dict):
                continue
            raw = item.get("raw_decision", item.get("decision"))
            valid_decisions.append(raw)
        if valid_decisions and not any(_decision_equal(decision, x) for x in valid_decisions):
            return False

        logger.info(
            "approval_router.resolve_action action_id=%s request_id=%r request_id_type=%s decision=%s",
            action_id,
            request_id,
            type(request_id).__name__,
            decision,
        )
        result = _build_result_payload(str(payload.get("approval_type", "")), decision, reason)
        self.client.respond_request_result(request_id=request_id, result=result)
        self.state.update_action_status(action_id, "done")
        return True


def _decision_equal(a: Any, b: Any) -> bool:
    if a is b:
        return True
    if type(a) is type(b):
        return a == b
    try:
        return json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)
    except Exception:
        return a == b


def _build_result_payload(method: str, decision: Any, reason: str) -> dict[str, Any]:
    if method == "mcpServer/elicitation/request":
        if isinstance(decision, dict):
            return decision
        return {"action": str(decision), "content": None, "_meta": None}
    if method == "item/tool/requestUserInput":
        if isinstance(decision, dict):
            return decision
        return {"answers": {}}
    if method == "item/permissions/requestApproval":
        if isinstance(decision, dict):
            return decision
        return {"permissions": {}, "scope": "turn"}
    result = {"decision": decision}
    if reason:
        result["reason"] = reason
    return result
