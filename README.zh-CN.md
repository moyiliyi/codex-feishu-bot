[English](README.md) | 中文
# Codex 飞书机器人

一个面向 **Codex CLI / Codex App Server** 的飞书桥接项目。

本项目提供一条自托管、可集成的实现路径：把 Codex 的审批和会话状态推送到飞书，并在飞书直接回传下一步指令，形成可运营的移动协同链路。

## 安装

 - 安装指南 [INSTALL.zh-CN.md](./INSTALL.zh-CN.md)

## 这个项目解决什么问题

官方 Codex 手机 App 证明了移动协同开发的需求，但在部分团队场景中，仍需要更可控的自托管集成方案。

本项目的定位：

- **不限定运行设备**。(已通过测试：Linux / macOS）
- 可基于 **Codex CLI + App Server** 运行，不要求必须使用桌面 App 形态
- 对账号环境无额外耦合要求（按你的基础环境自行部署）
- 通过飞书卡片完成审批回传与下一轮输入

## 适用场景

- 想在手机上快速处理 Codex 审批
- 希望在离开电脑时仍可继续推进对话线程
- 团队需要把 Codex 进度和关键操作同步到飞书
- 需要一个可自托管、可改造的 Codex 消息中转层


## 核心功能

- 审批请求推送：将 Codex 的审批请求转为飞书交互卡片
- 审批结果回传：飞书点击后回写到 App Server JSON-RPC
- 对话结束通知：收到 `turn/completed` 后自动推送继续卡片
- 飞书继续对话：在飞书输入下一步 prompt，触发 `turn/start`
- 多会话监听：支持 alias 到 thread 的 JSON 映射
- 本地状态持久化：去重与 pending action 管理


## 与官方 Codex 手机 App 的差异
> 官方手机 App 常见限制：

> - 需要在 Mac 端启动对应程序，且必须是 Codex App，而不是 CLI
> - 需要手机端与电脑端登录同一账号（对中转/代运维场景不友好）
> - 手机端本身也需要科学上网

本项目（Codex Feishu Relay）的特点：

- 服务器可部署在 Linux 或 macOS
- 可以直接结合 Codex CLI 的工作流
- 账号环境不做强绑定要求（由你自己的部署环境决定）
- 你只需要保证服务端能访问 Codex App Server 和飞书开放平台

## 实现路径（技术架构）

运行时，桥接服务维持两条长连接：一条连接飞书（接收机器人事件和卡片回调），一条连接 Codex App Server（接收 JSON-RPC 事件）。服务会附着到已配置的 Codex 线程，将审批>请求和对话结束事件转换为飞书交互卡片，再把飞书上的用户操作转换回 JSON-RPC 调用。

端到端流程：

1. 启动桥接服务：飞书 WS 事件客户端 + App Server WS 客户端。
2. 对监听线程执行 `thread/resume`，建立事件接收通道。
3. 从 App Server 接收审批事件或 `turn/completed` 事件。
4. 将待处理动作写入本地状态，并推送飞书交互卡片。
5. 处理飞书卡片回调并回写 JSON-RPC：
   - 审批回调 -> 响应对应 request id
   - 继续回调 -> 携带用户 prompt 发送 `turn/start`

## 项目结构

```text
.
├── app.py                         # 入口：组装飞书服务与 App Server 桥接
├── config.py                      # 环境变量配置与监听线程映射加载
├── bridge_appserver/
│   ├── ws_bridge.py               # WS 生命周期、重连、线程附着、事件分发
│   ├── events.py                  # JSON-RPC 报文解析为领域事件
│   ├── approval_router.py         # 审批事件 -> 飞书卡片 -> JSON-RPC 回传
│   ├── turn_router.py             # 对话结束 -> 继续卡片 -> turn/start
│   └── client.py                  # JSON-RPC 请求与通知封装
├── codex_bridge/
│   ├── state_store.py             # pending action 持久化与去重状态管理
│   └── models.py                  # 状态模型定义
├── INSTALL.md                     # English installation guide
└── INSTALL.zh-CN.md               # 中文安装文档
```



