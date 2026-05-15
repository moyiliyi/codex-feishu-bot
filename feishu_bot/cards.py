from __future__ import annotations

import json

from bridge_appserver.events import encode_option_token


def _short_text(text: str, limit: int = 36) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."


def approval_card(
    action_id: str,
    session_id: str,
    command: str,
    justification: str,
    session_label: str,
    header_template: str,
    options: list[dict[str, object]] | None = None,
) -> str:
    normalized = options or []
    buttons = []
    option_details = []
    for idx, item in enumerate(normalized, start=1):
        decision = str(item.get("decision", "")).strip() or str(item.get("label", "")).strip()
        raw_decision = item.get("raw_decision", decision)
        label = str(item.get("label", "")).strip() or decision
        if not decision:
            continue
        token = str(item.get("token") or encode_option_token(raw_decision))
        compact_label = _short_text(label, limit=36) or f"选项 {idx}"
        button_text = f"{idx}. {compact_label}"
        raw_preview = json.dumps(raw_decision, ensure_ascii=False)
        if len(raw_preview) > 900:
            raw_preview = raw_preview[:900] + "...(truncated)"
        option_details.append({"tag": "markdown", "content": f"**选项 {idx}**: {label}\n```json\n{raw_preview}\n```"})
        buttons.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": button_text},
                "type": "default",
                "width": "fill",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {"action": "approval_decision", "action_id": action_id, "decision_token": token},
                    }
                ],
            }
        )
    if not buttons:
        option_details = [{"tag": "markdown", "content": "<font color='red'>未收到可用审批选项，请在本地终端处理审批。</font>"}]
    button_rows = []
    for btn in buttons:
        button_rows.append(
            {
                "tag": "column_set",
                "flex_mode": "stretch",
                "horizontal_align": "left",
                "columns": [
                    {
                        "tag": "column",
                        "width": "auto",
                        "elements": [btn],
                        "vertical_spacing": "8px",
                        "horizontal_align": "left",
                        "vertical_align": "top",
                    }
                ],
                "margin": "0px 0px 0px 0px",
            }
        )
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"会话 {session_label} 审批请求"},
            "template": header_template,
        },
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": f"审批内容:\n```bash\n{command}\n```"},
                {"tag": "markdown", "content": f"<font color='grey'>审批说明: {justification or '无'}</font>"},
            ]
            + option_details
            + button_rows,
        },
    }
    return json.dumps(card, ensure_ascii=False)


def complete_card(
    action_id: str,
    session_id: str,
    last_message: str,
    session_label: str,
    header_template: str,
) -> str:
    content = last_message if len(last_message) < 3500 else last_message[:3500] + "\n...(truncated)"
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"会话 {session_label} 已结束"},
            "template": header_template,
        },
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": f"上一条消息记录：\n```text\n{content or '(空)'}\n```"},
                {
                    "tag": "form",
                    "name": "message_form",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "message_input",
                            "width": "fill",
                            "placeholder": {"tag": "plain_text", "content": "输入消息..."},
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "发送"},
                            "type": "primary_filled",
                            "width": "fill",
                            "form_action_type": "submit",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {"action": "send_next_prompt", "action_id": action_id},
                                }
                            ],
                        },
                    ],
                },
            ],
        },
    }
    return json.dumps(card, ensure_ascii=False)


def submitted_card(session_id: str, submitted_prompt: str, session_label: str, header_template: str) -> str:
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"会话 {session_label} 请求已提交"},
            "template": header_template,
        },
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": "已提交到会话，等待 AI 返回。"},
                {"tag": "markdown", "content": f"本次消息：\n```text\n{submitted_prompt}\n```"},
            ],
        },
    }
    return json.dumps(card, ensure_ascii=False)


def approval_submitted_card(session_id: str, decision: object, session_label: str, header_template: str) -> str:
    card = {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"会话 {session_label} 审批已提交"},
            "template": header_template,
        },
        "body": {
            "direction": "vertical",
            "elements": [
                {"tag": "markdown", "content": "审批结果已提交到会话，等待执行结果。"},
                {"tag": "markdown", "content": f"本次选项：\n```json\n{json.dumps(decision, ensure_ascii=False)}\n```"},
            ],
        },
    }
    return json.dumps(card, ensure_ascii=False)
