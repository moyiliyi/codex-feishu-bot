from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ApprovalEvent:
    session_id: str
    turn_id: str
    call_id: str
    command: str
    justification: str
    raw_arguments: str
    event_key: str


@dataclass(frozen=True)
class TurnCompleteEvent:
    session_id: str
    turn_id: str
    last_agent_message: str
    event_key: str


@dataclass(frozen=True)
class WatchedSession:
    session_id: str
    target_receive_id_type: str
    target_receive_id: str
    session_alias: str = ""
    header_template: str = "blue"


@dataclass(frozen=True)
class PendingCardAction:
    action_id: str
    session_id: str
    action_type: str
    payload_json: str
    status: str
    source_receive_id_type: Optional[str] = None
    source_receive_id: Optional[str] = None
