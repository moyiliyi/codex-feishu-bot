from __future__ import annotations

import glob
import os
from typing import Dict


def discover_sessions(codex_home: str) -> Dict[str, str]:
    pattern = os.path.join(codex_home, "sessions", "*", "*", "*", "rollout-*.jsonl")
    result: Dict[str, str] = {}
    for path in glob.glob(pattern):
        filename = os.path.basename(path)
        if not filename.endswith('.jsonl'):
            continue
        # rollout-2026-...-<session_id>.jsonl
        session_id = filename.rsplit('-', 1)[-1].replace('.jsonl', '')
        result[session_id] = path
    return result
