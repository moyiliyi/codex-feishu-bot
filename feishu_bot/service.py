from __future__ import annotations

import json
import logging
import uuid
from typing import Callable, Dict, Optional

import lark_oapi as lark
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse

from codex_bridge.codex_controller import CodexController
from codex_bridge.models import ApprovalEvent, PendingCardAction, TurnCompleteEvent, WatchedSession
from codex_bridge.state_store import StateStore
from feishu_bot.cards import approval_card, approval_submitted_card, complete_card, submitted_card
from bridge_appserver.approval_router import ApprovalCardRequest
from bridge_appserver.turn_router import ContinueCardRequest

logger = logging.getLogger(__name__)


HEADER_TEMPLATES = [
    "blue",
    "red",
    "yellow",
    "green",
    "wathet",
    "orange",
    "carmine",
    "turquoise",
    "violet",
    "grey",
    "indigo",
    "purple",
]


class FeishuBotService:
    def __init__(
        self,
        client: lark.Client,
        state: StateStore,
        codex: Optional[CodexController] = None,
        resolve_appserver_approval: Optional[Callable[[str, object, str], bool]] = None,
        continue_appserver_turn: Optional[Callable[[str, str], bool]] = None,
        resolve_session_ref: Optional[Callable[[str], str]] = None,
        list_configured_sessions: Optional[Callable[[], Dict[str, str]]] = None,
    ):
        self.client = client
        self.state = state
        self.codex = codex
        self.resolve_appserver_approval = resolve_appserver_approval
        self.continue_appserver_turn = continue_appserver_turn
        self.resolve_session_ref = resolve_session_ref
        self.list_configured_sessions = list_configured_sessions

    def _configured_map(self) -> Dict[str, str]:
        if not self.list_configured_sessions:
            return {}
        return self.list_configured_sessions() or {}

    def _alias_for_session(self, session_id: str) -> str:
        for alias, sid in self._configured_map().items():
            if sid == session_id:
                return alias
        return session_id

    def _pick_header_template(self) -> str:
        used = {x.header_template for x in self.state.list_watched() if x.header_template}
        for color in HEADER_TEMPLATES:
            if color not in used:
                return color
        return HEADER_TEMPLATES[0]

    def send_message(self, receive_id_type: str, receive_id: str, msg_type: str, content: str) -> None:
        logger.info(
            "send_message request: receive_id_type=%s receive_id=%s msg_type=%s content_len=%s",
            receive_id_type,
            receive_id,
            msg_type,
            len(content or ""),
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type(msg_type)
                .content(content)
                .build()
            )
            .build()
        )
        resp = self.client.im.v1.message.create(req)
        if not resp.success():
            logger.error(
                "send_message failed: receive_id_type=%s receive_id=%s msg_type=%s code=%s msg=%s",
                receive_id_type,
                receive_id,
                msg_type,
                getattr(resp, "code", ""),
                getattr(resp, "msg", ""),
            )
            raise RuntimeError(f"send failed: code={resp.code}, msg={resp.msg}")
        logger.info(
            "send_message success: receive_id_type=%s receive_id=%s msg_type=%s message_id=%s",
            receive_id_type,
            receive_id,
            msg_type,
            getattr(getattr(resp, "data", None), "message_id", ""),
        )

    def on_approval_event(self, event: ApprovalEvent) -> None:
        watch = self.state.get_watch(event.session_id)
        if not watch:
            return
        action_id = str(uuid.uuid4())
        self.state.put_action(
            PendingCardAction(
                action_id=action_id,
                session_id=event.session_id,
                action_type="approval",
                payload_json=json.dumps({"command": event.command}, ensure_ascii=False),
                status="pending",
                source_receive_id_type=watch.target_receive_id_type,
                source_receive_id=watch.target_receive_id,
            )
        )
        self.send_message(
            watch.target_receive_id_type,
            watch.target_receive_id,
            "interactive",
            approval_card(
                action_id,
                event.session_id,
                event.command,
                event.justification,
                watch.session_alias or self._alias_for_session(event.session_id),
                watch.header_template or "blue",
            ),
        )

    def on_complete_event(self, event: TurnCompleteEvent) -> None:
        watch = self.state.get_watch(event.session_id)
        if not watch:
            return
        action_id = str(uuid.uuid4())
        self.state.put_action(
            PendingCardAction(
                action_id=action_id,
                session_id=event.session_id,
                action_type="next_prompt",
                payload_json="{}",
                status="pending",
                source_receive_id_type=watch.target_receive_id_type,
                source_receive_id=watch.target_receive_id,
            )
        )
        self.send_message(
            watch.target_receive_id_type,
            watch.target_receive_id,
            "interactive",
            complete_card(
                action_id,
                event.session_id,
                event.last_agent_message,
                watch.session_alias or self._alias_for_session(event.session_id),
                watch.header_template or "blue",
            ),
        )

    def handle_text_command(self, chat_type: str, receive_id: str, text: str) -> str:
        cmd = text.strip()
        if cmd.startswith("/watch "):
            ref = cmd.split(" ", 1)[1].strip()
            session_id = self.resolve_session_ref(ref) if self.resolve_session_ref else ref
            if not session_id:
                return f"unknown session alias: {ref}"
            alias = ref if ref in self._configured_map() else self._alias_for_session(session_id)
            receive_id_type = "chat_id" if chat_type == "group" else "open_id"
            existing = self.state.get_watch(session_id)
            color = existing.header_template if existing else self._pick_header_template()
            self.state.set_watch(WatchedSession(session_id, receive_id_type, receive_id, alias, color))
            return f"watching session: {alias} -> {session_id} (color={color})"
        if cmd.startswith("/unwatch "):
            ref = cmd.split(" ", 1)[1].strip()
            session_id = self.resolve_session_ref(ref) if self.resolve_session_ref else ref
            if not session_id and ref:
                for w in self.state.list_watched():
                    if w.session_alias == ref:
                        session_id = w.session_id
                        break
            removed = self.state.remove_watch(session_id)
            return f"unwatch {'ok' if removed else 'not found'}: {ref} -> {session_id}"
        if cmd == "/list_watches":
            data = self.state.list_watched()
            if not data:
                return "no watched sessions"
            lines = []
            for x in data:
                alias = x.session_alias or self._alias_for_session(x.session_id)
                lines.append(
                    f"- {alias}\n  session_id: {x.session_id}\n  target: {x.target_receive_id_type}:{x.target_receive_id}\n  color: {x.header_template}"
                )
            return "\n".join(lines)
        if cmd == "/list_sessions":
            if not self.list_configured_sessions:
                return "no configured session aliases"
            data = self.list_configured_sessions()
            if not data:
                return "no configured session aliases"
            lines = [f"- {alias} -> {session_id}" for alias, session_id in sorted(data.items())]
            return "\n".join(lines)
        return "unsupported command"

    def handle_card_action(self, action_value: dict, form_value: dict | None) -> P2CardActionTriggerResponse:
        action = action_value.get("action")
        action_id = action_value.get("action_id")
        record = self.state.get_action(action_id)
        if not record:
            return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "action expired"}})

        if action == "approval_decision":
            payload = json.loads(record.payload_json)
            decision_value = self._decode_approval_decision(action_value, payload)
            if decision_value is None:
                return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "审批选项无效"}})
            reason = ""
            logger.info(
                "【收到请求】session_id=%s 消息=%s",
                record.session_id,
                f"审批决策 decision={decision_value!r}",
            )
            if record.action_type == "appserver_approval" and self.resolve_appserver_approval:
                ok = self.resolve_appserver_approval(action_id, decision_value, reason)
                if not ok:
                    return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "审批已处理或无效"}})
            else:
                if not self.codex:
                    return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "controller unavailable"}})
                self.codex.resume_for_approval(record.session_id, payload.get("command", ""), decision_value, reason)
                self.state.update_action_status(action_id, "done")
            verdict = f"已提交审批选项: {decision_value}"
            watch = self.state.get_watch(record.session_id)
            label = watch.session_alias if watch and watch.session_alias else self._alias_for_session(record.session_id)
            template = watch.header_template if watch else "green"
            updated = json.loads(approval_submitted_card(record.session_id, decision_value, label, template))
            return P2CardActionTriggerResponse(
                {
                    "toast": {"type": "info", "content": verdict},
                    "card": {"type": "raw", "data": updated},
                }
            )

        if action == "send_next_prompt":
            prompt = ""
            if form_value:
                prompt = str(form_value.get("next_prompt", "")).strip() or str(form_value.get("message_input", "")).strip()
            if not prompt:
                return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "请输入指令"}})
            logger.info("【收到请求】session_id=%s 消息=%s", record.session_id, prompt)
            if record.action_type == "appserver_continue" and self.continue_appserver_turn:
                ok = self.continue_appserver_turn(action_id, prompt)
                if not ok:
                    return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "会话已失效或已处理"}})
            else:
                if not self.codex:
                    return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "controller unavailable"}})
                self.codex.resume_with_prompt(record.session_id, prompt)
                self.state.update_action_status(action_id, "done")
            watch = self.state.get_watch(record.session_id)
            label = watch.session_alias if watch and watch.session_alias else self._alias_for_session(record.session_id)
            template = watch.header_template if watch else "green"
            updated = json.loads(submitted_card(record.session_id, prompt, label, template))
            return P2CardActionTriggerResponse(
                {
                    "toast": {"type": "success", "content": "已发送"},
                    "card": {"type": "raw", "data": updated},
                }
            )

        return P2CardActionTriggerResponse({"toast": {"type": "warning", "content": "unsupported action"}})

    def _decode_approval_decision(self, action_value: dict, payload: dict) -> object | None:
        token = action_value.get("decision_token")
        if isinstance(token, str) and token.strip():
            for item in payload.get("options", []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("token", "")) == token:
                    return item.get("raw_decision", item.get("decision"))
            return None
        raw = action_value.get("decision")
        if raw is None or raw == "":
            return None
        return raw

    def send_appserver_approval_card(self, req: ApprovalCardRequest) -> None:
        watch = self.state.get_watch(req.thread_id)
        if not watch:
            logger.info("send_appserver_approval_card skipped: no watch for thread=%s", req.thread_id)
            return
        logger.info("【需要审批】session_id=%s 审批内容=%s", req.thread_id, req.summary)
        logger.info(
            "send_appserver_approval_card thread=%s -> %s:%s options_count=%s first_option=%s",
            req.thread_id,
            watch.target_receive_id_type,
            watch.target_receive_id,
            len(req.options or []),
            json.dumps((req.options or [None])[0], ensure_ascii=False) if req.options else "NONE",
        )
        label = watch.session_alias or self._alias_for_session(req.thread_id)
        self.send_message(
            watch.target_receive_id_type,
            watch.target_receive_id,
            "interactive",
            approval_card(req.action_id, req.thread_id, req.summary, "", label, watch.header_template or "blue", req.options),
        )

    def send_appserver_continue_card(self, req: ContinueCardRequest) -> None:
        watch = self.state.get_watch(req.thread_id)
        if not watch:
            logger.info("send_appserver_continue_card skipped: no watch for thread=%s", req.thread_id)
            return
        logger.info("【会话结束】session_id=%s 消息内容=%s", req.thread_id, req.last_message)
        logger.info("send_appserver_continue_card thread=%s -> %s:%s", req.thread_id, watch.target_receive_id_type, watch.target_receive_id)
        label = watch.session_alias or self._alias_for_session(req.thread_id)
        self.send_message(
            watch.target_receive_id_type,
            watch.target_receive_id,
            "interactive",
            complete_card(req.action_id, req.thread_id, req.last_message, label, watch.header_template or "blue"),
        )
