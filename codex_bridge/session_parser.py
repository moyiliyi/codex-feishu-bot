from __future__ import annotations

import json
import logging
from typing import Optional, Union

from .models import ApprovalEvent, TurnCompleteEvent

logger = logging.getLogger(__name__)


def _loads_arguments(arguments: str) -> dict:
    try:
        return json.loads(arguments)
    except Exception:
        logger.exception("failed to parse function call arguments as json")
        return {}


def parse_session_line(line: str, session_id: str) -> Optional[Union[ApprovalEvent, TurnCompleteEvent]]:
    try:
        obj = json.loads(line)
    except Exception:
        logger.exception("failed to parse session line as json: session_id=%s", session_id)
        return None

    record_type = obj.get("type")
    payload = obj.get("payload", {})

    if record_type == "response_item" and payload.get("type") == "function_call":
        args_raw = payload.get("arguments", "")
        args = _loads_arguments(args_raw)
        if args.get("sandbox_permissions") == "require_escalated":
            cmd = args.get("cmd", "")
            justification = args.get("justification", "")
            call_id = payload.get("call_id", "")
            event_key = f"approval:{session_id}:{call_id}:{cmd}"
            return ApprovalEvent(
                session_id=session_id,
                turn_id="",
                call_id=call_id,
                command=cmd,
                justification=justification,
                raw_arguments=args_raw,
                event_key=event_key,
            )

    if record_type == "event_msg" and payload.get("type") == "task_complete":
        turn_id = payload.get("turn_id", "")
        last = payload.get("last_agent_message", "")
        event_key = f"complete:{session_id}:{turn_id}"
        return TurnCompleteEvent(
            session_id=session_id,
            turn_id=turn_id,
            last_agent_message=last,
            event_key=event_key,
        )

    return None
