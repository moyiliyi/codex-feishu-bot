English | [中文](./README.zh-CN.md)

# Codex Feishu Bot

A Feishu/Lark bridge for **Codex CLI / Codex App Server** workflows.

This project is designed for developers who want a "Codex mobile control" experience but prefer a lightweight, open-source, self-hosted path. It pushes approval and turn-completion events from Codex to Feishu, then sends your next-step input back to the same Codex thread.

## Installation

- Setup guide: [INSTALL.md](./INSTALL.md)

## Why this exists

The official Codex mobile app validates demand for mobile-assisted coding workflows, but some teams need an integration path that is self-hosted, automation-friendly, and platform-flexible.


This repository focuses on a different path:

- Works with **Codex CLI + App Server bridge flow**
- Works on **All Platform**. (Tested with Linux and macOS now)
- No strict runtime device binding in project design
- Feishu as the control surface for approvals and next-turn prompts


## Key features

- Approval push: forwards approval requests to Feishu interactive cards.
- Approval callback: sends approve/deny decisions back to App Server JSON-RPC.
- Turn completion push: notifies when a turn is completed.
- Continue-in-Feishu: submit the next prompt from Feishu and trigger `turn/start`.
- Multi-session mapping: supports alias-to-thread mapping from JSON config.
- Dedup and state persistence: avoids duplicated actions via local state store.

## Comparison: official mobile app vs this project

| Capability | Official Codex Mobile App (by 26.05.15)| Codex Feishu Relay |
| --- | --- | --- |
| Main interaction surface | Official mobile app | Feishu/Lark cards + chat |
| Linux/macOS deployment | Depends on official app flow | Yes |
| CLI-oriented integration | Limited | Yes |
| Network dependency | Requires stable access to OpenAI services | Requires reachability to your App Server + Feishu |

## How it works (implementation path)


At runtime, the bridge keeps two long-lived connections: one to Feishu for bot events/card callbacks, and one to Codex App Server for JSON-RPC events. The bridge subscribes to configured Codex threads, converts approval and turn-completion events into Feishu cards, then converts user actions in Feishu back into JSON-RPC calls.

End-to-end flow:

1. Start bridge services: Feishu WS event client + App Server WS client.
2. Attach to watched threads using `thread/resume`.
3. Receive approval or `turn/completed` events from App Server.
4. Persist a pending action in local state and push an interactive Feishu card.
5. Handle card callbacks and send the corresponding JSON-RPC result:
   - approval callback -> respond to request id
   - continue callback -> send `turn/start` with user prompt


```text
.
├── app.py                         # Entry point: wires Feishu service and App Server bridge
├── config.py                      # Environment config and session-map loading
├── bridge_appserver/
│   ├── ws_bridge.py               # WS lifecycle, reconnect loop, thread attach, event dispatch
│   ├── events.py                  # Parse JSON-RPC payloads into domain events
│   ├── approval_router.py         # Approval event -> Feishu card -> JSON-RPC response
│   ├── turn_router.py             # Turn completed -> continue card -> turn/start
│   └── client.py                  # JSON-RPC request/notification wrapper
├── codex_bridge/
│   ├── state_store.py             # Local persistence for pending actions and dedup
│   └── models.py                  # Typed state models
├── INSTALL.md                     # English installation guide
└── INSTALL.zh-CN.md               # 中文安装文档
```

## Use cases

- Handle Codex approvals from your phone through Feishu
- Get notified when Codex finishes a turn and continue immediately
- Operate coding sessions when you are away from the laptop UI
- Build a team-internal notification workflow around Codex threads

## Current scope

- Focused on Feishu/Lark workflow
- Uses WebSocket + JSON-RPC bridge semantics from Codex App Server
- Not intended as a replacement for official products; it is an open integration layer

## License

Add your preferred open-source license (for example MIT) before public release.
