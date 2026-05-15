from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: Any
    thread_id: str
    turn_id: str
    approval_type: str
    summary: str
    raw_method: str
    options: list[dict[str, Any]]


@dataclass(frozen=True)
class TurnCompleted:
    thread_id: str
    turn_id: str
    last_assistant_message: str


AppServerEvent = ApprovalRequest | TurnCompleted
logger = logging.getLogger(__name__)


def encode_option_token(raw_decision: Any) -> str:
    payload = json.dumps(raw_decision, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"opt_{digest[:24]}"


def _safe_get(d: dict[str, Any], *keys: str, default: Any = "") -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _extract_last_message_from_turn_items(params: dict[str, Any]) -> str:
    turn = params.get("turn")
    if not isinstance(turn, dict):
        return ""
    items = turn.get("items")
    if not isinstance(items, list):
        return ""

    # Walk from the tail and pick the latest agent message text.
    for raw in reversed(items):
        if not isinstance(raw, dict):
            continue
        item_type = raw.get("type")
        if item_type != "agentMessage":
            continue
        text = raw.get("text")
        if isinstance(text, str) and text.strip():
            return text
    return ""


def parse_appserver_event(message: dict[str, Any]) -> Optional[AppServerEvent]:
    method = str(message.get("method", ""))
    req_id = message.get("id")
    params = message.get("params", {})

    is_item_approval = method.startswith("item/") and method.endswith("/requestApproval")
    is_mcp_elicitation = method == "mcpServer/elicitation/request"
    is_legacy_approval = method in {"applyPatchApproval", "execCommandApproval"}
    is_user_input = method == "item/tool/requestUserInput"
    if req_id is not None and (is_item_approval or is_mcp_elicitation or is_legacy_approval or is_user_input):
        thread_id = str(_safe_get(params, "thread_id") or _safe_get(params, "threadId"))
        turn_id = str(_safe_get(params, "turn_id") or _safe_get(params, "turnId"))
        summary = str(
            _safe_get(params, "summary")
            or _safe_get(params, "command")
            or _safe_get(params, "message")
            or _safe_get(params, "prompt")
            or _safe_get(params, "title")
            or _safe_get(params, "reason")
            or "approval requested"
        )
        options = _extract_approval_options(method, params)
        if is_mcp_elicitation:
            schema = _first_dict(
                params.get("requestedSchema"),
                params.get("requested_schema"),
                params.get("schema"),
                _safe_get(params, "request", "requestedSchema", default=None),
                _safe_get(params, "request", "requested_schema", default=None),
                _safe_get(params, "request", "schema", default=None),
            )
            logger.info(
                "mcp elicitation parsed: request_id=%r thread_id=%s turn_id=%s params_keys=%s schema_keys=%s options_count=%s sample_option=%s",
                req_id,
                thread_id,
                turn_id,
                sorted(params.keys()) if isinstance(params, dict) else [],
                sorted(schema.keys()) if isinstance(schema, dict) else [],
                len(options),
                json.dumps(options[0], ensure_ascii=False) if options else "NONE",
            )
        return ApprovalRequest(
            request_id=req_id,
            thread_id=thread_id,
            turn_id=turn_id,
            approval_type=method,
            summary=summary,
            raw_method=method,
            options=options,
        )

    if method == "turn/completed":
        thread_id = str(_safe_get(params, "thread_id") or _safe_get(params, "threadId"))
        turn_id = str(
            _safe_get(params, "turn_id")
            or _safe_get(params, "turnId")
            or _safe_get(params, "turn", "id")
        )
        last_message = str(
            _safe_get(params, "last_assistant_message")
            or _safe_get(params, "lastAssistantMessage")
            or _safe_get(params, "assistant_message")
            or _safe_get(params, "assistantMessage")
            or _extract_last_message_from_turn_items(params)
            or ""
        )
        return TurnCompleted(thread_id=thread_id, turn_id=turn_id, last_assistant_message=last_message)

    return None


def _extract_approval_options_by_method(method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        params.get("options"),
        params.get("choices"),
        params.get("decisions"),
        params.get("allowedDecisions"),
        params.get("availableDecisions"),
        _safe_get(params, "approval", "options", default=None),
        _safe_get(params, "approval", "choices", default=None),
        _safe_get(params, "request", "options", default=None),
        _safe_get(params, "request", "choices", default=None),
    ]
    for raw in candidates:
        if not isinstance(raw, list):
            continue
        normalized: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                decision = item.strip()
                if decision:
                    normalized.append(
                        {
                            "decision": decision,
                            "label": decision,
                            "raw_decision": item,
                            "token": encode_option_token(item),
                        }
                    )
                continue
            if not isinstance(item, dict):
                continue
            if len(item) == 1:
                only_key = next(iter(item.keys()))
                only_val = item.get(only_key)
                if isinstance(only_val, dict):
                    normalized.append(
                        {
                            "decision": json.dumps(item, ensure_ascii=False, sort_keys=True),
                            "label": only_key,
                            "raw_decision": item,
                            "token": encode_option_token(item),
                        }
                    )
                    continue
            decision = str(
                item.get("decision")
                or item.get("id")
                or item.get("value")
                or item.get("key")
                or ""
            ).strip()
            label = str(item.get("label") or item.get("title") or decision).strip()
            if decision:
                normalized.append(
                    {
                        "decision": decision,
                        "label": label or decision,
                        "raw_decision": decision,
                        "token": encode_option_token(decision),
                    }
                )
        if normalized:
            return normalized
    schema_options = _extract_options_from_schema(params)
    if schema_options:
        return schema_options
    method_options = _extract_method_fallback_options(method, params)
    if method_options:
        return method_options
    return []


def _extract_approval_options(method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return _extract_approval_options_by_method(method, params)


def _extract_method_fallback_options(method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if method == "mcpServer/elicitation/request":
        return _extract_mcp_elicitation_fallback_options(params)
    if method == "item/permissions/requestApproval":
        requested = params.get("permissions")
        if requested is None:
            requested = {}
        return [
            _build_option({"permissions": requested, "scope": "turn"}, "accept (turn)"),
            _build_option({"permissions": requested, "scope": "session"}, "accept (session)"),
            _build_option({"permissions": {}, "scope": "turn"}, "decline"),
            _build_option({"permissions": {}, "scope": "turn", "strictAutoReview": False}, "cancel"),
        ]
    if method in {"applyPatchApproval", "execCommandApproval"}:
        return [
            _build_option("approved", "approved"),
            _build_option("approved_for_session", "approved_for_session"),
            _build_option("denied", "denied"),
            _build_option("abort", "abort"),
        ]
    if method == "item/tool/requestUserInput":
        return _extract_request_user_input_options(params)
    return []


def _extract_mcp_elicitation_fallback_options(params: dict[str, Any]) -> list[dict[str, Any]]:
    message_only_schema = False
    req_schema = params.get("requestedSchema")
    if isinstance(req_schema, dict):
        props = req_schema.get("properties")
        message_only_schema = isinstance(props, dict) and len(props) == 0
    meta = params.get("_meta")
    persist_values: set[str] = set()
    if isinstance(meta, dict):
        persist = meta.get("persist")
        if isinstance(persist, str):
            persist_values.add(persist)
        elif isinstance(persist, list):
            persist_values.update([str(x) for x in persist if isinstance(x, str)])
    options = [_build_option({"action": "accept", "content": None, "_meta": None}, "Allow")]
    if "session" in persist_values:
        options.append(
            _build_option(
                {"action": "accept", "content": None, "_meta": {"persist": "session"}},
                "Allow for this session",
            )
        )
    if "always" in persist_values:
        options.append(
            _build_option(
                {"action": "accept", "content": None, "_meta": {"persist": "always"}},
                "Always allow",
            )
        )
    if message_only_schema:
        options.append(_build_option({"action": "cancel", "content": None, "_meta": None}, "Cancel"))
    else:
        options.append(_build_option({"action": "decline", "content": None, "_meta": None}, "Deny"))
        options.append(_build_option({"action": "cancel", "content": None, "_meta": None}, "Cancel"))
    return options


def _extract_request_user_input_options(params: dict[str, Any]) -> list[dict[str, Any]]:
    questions = params.get("questions")
    if not isinstance(questions, list) or not questions:
        return []
    result: list[dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or "").strip()
        if not qid:
            continue
        options = q.get("options")
        if isinstance(options, list) and options:
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                label = str(opt.get("label") or "").strip()
                if not label:
                    continue
                answer_payload = {"answers": {qid: {"answers": [label]}}}
                result.append(_build_option(answer_payload, f"{qid}: {label}"))
            continue
        # No predefined options; provide a noop-style placeholder to keep flow unblocked.
        answer_payload = {"answers": {qid: {"answers": [""]}}}
        result.append(_build_option(answer_payload, f"{qid}: (empty answer)"))
    return result


def _extract_options_from_schema(params: dict[str, Any]) -> list[dict[str, Any]]:
    schema_candidates = [
        params.get("requestedSchema"),
        params.get("requested_schema"),
        params.get("schema"),
        _safe_get(params, "request", "requestedSchema", default=None),
        _safe_get(params, "request", "requested_schema", default=None),
        _safe_get(params, "request", "schema", default=None),
    ]
    for schema in schema_candidates:
        if not isinstance(schema, dict):
            continue
        options = _options_from_json_schema(schema)
        if options:
            return options
    return []


def _first_dict(*vals: Any) -> dict[str, Any] | None:
    for v in vals:
        if isinstance(v, dict):
            return v
    return None


def _options_from_json_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    # 1) Direct enum on schema root.
    root_enum = schema.get("enum")
    if isinstance(root_enum, list) and root_enum:
        return [_build_option(x, str(x)) for x in root_enum]

    # 2) oneOf/anyOf/choices patterns on schema root.
    root_alts = schema.get("oneOf") if isinstance(schema.get("oneOf"), list) else schema.get("anyOf")
    if isinstance(root_alts, list) and root_alts:
        built = _build_options_from_alternatives(root_alts)
        if built:
            return built

    # 3) Typical requestedSchema: object with one field.
    props = schema.get("properties")
    if isinstance(props, dict) and props:
        required = schema.get("required")
        preferred_keys: list[str] = []
        if isinstance(required, list):
            preferred_keys.extend([str(x) for x in required if isinstance(x, str)])
        preferred_keys.extend([str(k) for k in props.keys() if isinstance(k, str)])

        seen = set()
        for key in preferred_keys:
            if key in seen:
                continue
            seen.add(key)
            field = props.get(key)
            if not isinstance(field, dict):
                continue
            enum_vals = field.get("enum")
            if isinstance(enum_vals, list) and enum_vals:
                labels = field.get("enumNames") if isinstance(field.get("enumNames"), list) else field.get("enum_titles")
                out = []
                for i, val in enumerate(enum_vals):
                    label = str(val)
                    if isinstance(labels, list) and i < len(labels):
                        label = str(labels[i]) or label
                    out.append(_build_option(val, label))
                if out:
                    return out
            alts = field.get("oneOf") if isinstance(field.get("oneOf"), list) else field.get("anyOf")
            if isinstance(alts, list) and alts:
                built = _build_options_from_alternatives(alts)
                if built:
                    return built

    return []


def _build_options_from_alternatives(alts: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in alts:
        if not isinstance(item, dict):
            continue
        if "const" in item:
            val = item.get("const")
            label = str(item.get("title") or item.get("label") or item.get("description") or val)
            out.append(_build_option(val, label))
            continue
        if "enum" in item and isinstance(item.get("enum"), list):
            for val in item.get("enum"):
                label = str(item.get("title") or item.get("label") or item.get("description") or val)
                out.append(_build_option(val, label))
    return out


def _build_option(raw: Any, label: str) -> dict[str, Any]:
    decision = str(raw).strip()
    display = label.strip() or decision
    return {
        "decision": decision,
        "label": display,
        "raw_decision": raw,
        "token": encode_option_token(raw),
    }
