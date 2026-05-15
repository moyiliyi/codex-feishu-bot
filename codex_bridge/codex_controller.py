from __future__ import annotations

import shlex
import subprocess
import json
from typing import Any


class CodexController:
    def __init__(self, codex_bin: str = "codex") -> None:
        self.codex_bin = codex_bin

    def resume_with_prompt(self, session_id: str, prompt: str) -> subprocess.CompletedProcess:
        cmd = [self.codex_bin, "exec", "resume", session_id, prompt]
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def build_approval_prompt(self, command: str, decision: Any, reason: str) -> str:
        verdict = json.dumps(decision, ensure_ascii=False)
        return (
            "External approval callback received.\\n"
            f"Command: {command}\\n"
            f"Decision: {verdict}\\n"
            f"Reason: {reason or 'N/A'}\\n"
            "Please continue the task accordingly."
        )

    def resume_for_approval(self, session_id: str, command: str, decision: Any, reason: str) -> subprocess.CompletedProcess:
        return self.resume_with_prompt(session_id, self.build_approval_prompt(command, decision, reason))

    def debug_cmdline(self, session_id: str, prompt: str) -> str:
        return " ".join(shlex.quote(x) for x in [self.codex_bin, "exec", "resume", session_id, prompt])
