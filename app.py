from __future__ import annotations

import json
import logging
import os
import time

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from codex_bridge.state_store import StateStore
from config import Config, load_listen_session_ids, load_listen_session_map, resolve_session_ref, validate_config
from bridge_appserver.approval_router import ApprovalRouter
from bridge_appserver.client import AppServerClient
from bridge_appserver.turn_router import TurnRouter
from bridge_appserver.ws_bridge import AppServerWsBridge, WsTransport
from feishu_bot.service import FeishuBotService

logger = logging.getLogger(__name__)

validate_config()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

state = StateStore(Config.STATE_PATH)
client = lark.Client.builder().app_id(Config.APP_ID).app_secret(Config.APP_SECRET).build()
service = FeishuBotService(
    client,
    state,
    codex=None,
    resolve_session_ref=lambda ref: resolve_session_ref(Config.LISTEN_SESSION_ID_PATH, ref),
    list_configured_sessions=lambda: load_listen_session_map(Config.LISTEN_SESSION_ID_PATH),
)
transport = WsTransport()
appserver_client = AppServerClient(transport)
approval_router = ApprovalRouter(state, appserver_client, send_card=service.send_appserver_approval_card)
turn_router = TurnRouter(state, appserver_client, send_card=service.send_appserver_continue_card)
service.resolve_appserver_approval = approval_router.resolve_action
service.continue_appserver_turn = turn_router.continue_with_prompt
bridge = AppServerWsBridge(
    ws_url=Config.APP_SERVER_WS_URL,
    client=appserver_client,
    transport=transport,
    get_listen_session_ids=lambda: load_listen_session_ids(Config.LISTEN_SESSION_ID_PATH),
    on_approval=approval_router.on_approval_request,
    on_turn_completed=turn_router.on_turn_completed,
)


def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
    text = ""
    try:
        text = json.loads(data.event.message.content).get("text", "").strip()
    except Exception:
        logger.exception("failed to parse incoming feishu message content")
        return
    if not text.startswith("/"):
        return

    chat_type = data.event.message.chat_type
    chat_id = data.event.message.chat_id
    open_id = data.event.sender.sender_id.open_id
    receive_id = chat_id if chat_type == "group" else open_id
    reply = service.handle_text_command(chat_type, receive_id, text)
    if chat_type == "group":
        service.send_message("chat_id", chat_id, "text", json.dumps({"text": reply}, ensure_ascii=False))
    else:
        service.send_message("open_id", open_id, "text", json.dumps({"text": reply}, ensure_ascii=False))


def do_p2_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    action = data.event.action
    return service.handle_card_action(action.value or {}, action.form_value)


event_handler = (
    lark.EventDispatcherHandler.builder("", "")
    .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
    .register_p2_card_action_trigger(do_p2_card_action_trigger)
    .build()
)

ws_client = lark.ws.Client(
    Config.APP_ID,
    Config.APP_SECRET,
    event_handler=event_handler,
    log_level=lark.LogLevel.INFO,
)


def main() -> None:
    print(f"[bridge] APP_SERVER_WS_URL={Config.APP_SERVER_WS_URL}")
    print(f"[bridge] LISTEN_SESSION_ID_PATH={Config.LISTEN_SESSION_ID_PATH}")
    print(f"[bridge] loaded session map={load_listen_session_map(Config.LISTEN_SESSION_ID_PATH)}")
    bridge.start()
    if os.getenv("SKIP_FEISHU_WS", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        print("[bridge] SKIP_FEISHU_WS enabled, feishu ws client not started")
        while True:
            time.sleep(1)
    ws_client.start()


if __name__ == "__main__":
    main()
