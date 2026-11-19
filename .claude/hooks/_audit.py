"""Shared by guard.py and audit.py: append one line per tool call to the audit log.

The log never stores the tool input itself, only a SHA-256 of it, so a secret the agent tried
to read or send never lands in the log. Stdlib only, so the hooks run on any python3.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def log_path() -> Path:
    base = os.environ.get("AGENT_AUDIT_DIR") or os.path.join(
        os.environ.get("CLAUDE_PROJECT_DIR", "."), ".agent-audit"
    )
    return Path(base) / "tool_calls.jsonl"


def input_hash(tool_input: Any) -> str:
    canonical = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def record(event: dict[str, Any], decision: str, reason: str | None = None) -> None:
    entry: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (py<3.11)
        "session_id": event.get("session_id"),
        "tool": event.get("tool_name"),
        "input_hash": input_hash(event.get("tool_input")),
        "decision": decision,
    }
    if reason:
        entry["reason"] = reason
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
