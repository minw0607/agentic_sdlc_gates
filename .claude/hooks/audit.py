"""PostToolUse audit: append every tool call that ran to .agent-audit/tool_calls.jsonl.

Calls the guard blocked never run, so guard.py logs those itself with decision "denied". This
hook logs the rest with decision "allowed". It never blocks and never fails the tool call.
"""

from __future__ import annotations

import json
import sys

try:
    import _audit
except Exception:  # never fail the tool call; main() reports it
    _audit = None  # type: ignore[assignment]


def main() -> int:
    try:
        if _audit is None:
            raise RuntimeError("the _audit module is missing")
        event = json.load(sys.stdin)
        if isinstance(event, dict):
            _audit.record(event, "allowed")
    except Exception as e:
        print(f"audit hook could not record this call: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
