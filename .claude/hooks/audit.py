"""PostToolUse audit: append every tool call that ran to .agent-audit/tool_calls.jsonl.

Calls the guard blocked never run, so guard.py logs those itself with decision "denied". This
hook logs the rest with decision "allowed". It never blocks and never fails the tool call.
"""

from __future__ import annotations

import json
import sys

import _audit


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if isinstance(event, dict):
            _audit.record(event, "allowed")
    except (ValueError, OSError) as e:
        print(f"audit hook could not record this call: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
