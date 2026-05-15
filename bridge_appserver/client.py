from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from typing import Any, Protocol


class Transport(Protocol):
    def send(self, payload: dict[str, Any]) -> None:
        ...


@dataclass(frozen=True)
class JsonRpcRequest:
    method: str
    params: dict[str, Any]
    id: str | None = None

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": self.method, "params": self.params}
        if self.id is not None:
            payload["id"] = self.id
        return payload


class InMemoryTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


class AppServerClient:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self._ids = count(1)

    def send(self, req: JsonRpcRequest) -> None:
        self.transport.send(req.as_payload())

    def call(self, method: str, params: dict[str, Any]) -> str:
        req_id = str(next(self._ids))
        self.send(JsonRpcRequest(method=method, params=params, id=req_id))
        return req_id

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self.send(JsonRpcRequest(method=method, params=params, id=None))

    def initialize(self, client_name: str = "feishu-bridge") -> str:
        return self.call(
            "initialize",
            {
                "clientInfo": {
                    "name": client_name,
                    "version": "0.1.0",
                }
            },
        )

    def initialized(self) -> None:
        self.notify("initialized", {})

    def thread_start(self) -> str:
        return self.call("thread/start", {})

    def thread_resume(self, thread_id: str) -> str:
        return self.call("thread/resume", {"threadId": thread_id, "thread_id": thread_id})

    def thread_subscribe(self, thread_id: str) -> str:
        return self.call("thread/subscribe", {"threadId": thread_id, "thread_id": thread_id})

    def turn_start(self, thread_id: str, user_input: str) -> str:
        return self.call(
            "turn/start",
            {
                "threadId": thread_id,
                "thread_id": thread_id,
                "input": [
                    {
                        "type": "text",
                        "text": user_input,
                    }
                ],
            },
        )

    def respond_approval(self, request_id: Any, decision: Any, reason: str = "") -> None:
        result = {"decision": decision}
        if reason:
            result["reason"] = reason
        self.transport.send({"jsonrpc": "2.0", "id": request_id, "result": result})

    def respond_request_result(self, request_id: Any, result: dict[str, Any]) -> None:
        self.transport.send({"jsonrpc": "2.0", "id": request_id, "result": result})
