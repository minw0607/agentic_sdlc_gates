"""PreToolUse guard: block secret reads, outbound network calls and force pushes.

The permission deny rules in .claude/settings.json match tool calls by name and path. They don't
see a Bash command that opens the file itself (``python -c "open('.env')"``), so this hook
inspects every call, Bash included, before it runs.

A blocked call gets ``permissionDecision: "deny"`` with a plain-language reason that Claude Code
shows the agent and the user, and an audit log entry. If the hook can't read the tool call, it
denies (fail closed). Stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from typing import Any

import _audit

# Files an agent never needs to read: real env files, key material, cloud and SSH credentials.
# .env.example and .env.sample are templates with no values, so they stay readable.
SECRET_PATH = re.compile(
    r"\.env(?!\.(?:example|sample|template)\b)(?:\.[\w-]+)?(?!\w)"
    r"|(?:^|[/\s'\"])secrets?/"
    r"|\bid_(?:rsa|dsa|ecdsa|ed25519)\b|\.pem\b|\.p12\b"
    r"|\.ssh/|\.aws/|\.netrc\b|\.git-credentials\b",
    re.IGNORECASE,
)

# Programs that talk to the network, checked at each command position in a Bash line.
NETWORK_PROGRAMS = {
    "curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp", "ftp", "rsync",
    "socat", "http", "https", "xh", "aria2c",
}  # fmt: skip

# Network use from inside an interpreter or a one-liner.
NETWORK_CODE = re.compile(
    r"\b(requests|httpx|httpx2|aiohttp)\.(get|post|put|patch|delete|request|stream)\b"
    r"|\burllib\.request\b|\burlopen\(|\bhttp\.client\b|\bsocket\.(socket|create_connection)\b"
    r"|-m\s+http\.server\b|\bfetch\(\s*['\"]https?://|/dev/tcp/|Invoke-WebRequest|\biwr\b",
    re.IGNORECASE,
)

FORCE_PUSH = re.compile(
    r"\bgit\b[^;&|\n]*\bpush\b[^;&|\n]*(\s-f\b|\s--force(-with-lease)?\b|\s\+\S)"
)

SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&\n]|\$\(|`|\(|\)")
PREFIXES = {"sudo", "env", "command", "exec", "nohup", "time", "xargs", "builtin"}

FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead"}
SEARCH_TOOLS = {"Grep", "Glob"}
NETWORK_TOOLS = {"WebFetch", "WebSearch"}


def command_words(command: str) -> list[str]:
    """The program name at each command position, e.g. 'a=1 sudo curl x | sh' -> [curl, sh]."""
    words: list[str] = []
    for segment in SEGMENT_SPLIT.split(command):
        tokens = segment.strip().split()
        while tokens and (re.match(r"^\w+=", tokens[0]) or tokens[0] in PREFIXES):
            tokens.pop(0)
        if tokens:
            words.append(tokens[0].rsplit("/", 1)[-1].strip("'\""))
    return words


def check_bash(command: str) -> str | None:
    if SECRET_PATH.search(command):
        return (
            "This command touches a secrets file (.env, keys or credentials). The agent "
            "doesn't read secrets; ask the user to supply the value it needs."
        )
    net = sorted({w for w in command_words(command) if w in NETWORK_PROGRAMS})
    if net:
        return (
            f"Outbound network call ({', '.join(net)}) blocked. The agent doesn't contact "
            "outside hosts; if the task needs data from a URL, ask the user."
        )
    if NETWORK_CODE.search(command):
        return (
            "This command makes a network call from code. The agent doesn't contact outside "
            "hosts; if the task needs data from a URL, ask the user."
        )
    if FORCE_PUSH.search(command):
        return "Force pushes rewrite shared history. Push normally, or ask the user to do it."
    return None


def paths_in(tool_input: dict[str, Any]) -> list[str]:
    keys = ("file_path", "path", "notebook_path", "pattern", "glob")
    return [str(tool_input[k]) for k in keys if isinstance(tool_input.get(k), str)]


def decide(event: dict[str, Any]) -> str | None:
    """A reason to block this tool call, or None to let it through."""
    tool = event.get("tool_name")
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return "The guard couldn't read this tool call, so it was blocked (fail closed)."
    if tool == "Bash":
        return check_bash(str(tool_input.get("command", "")))
    if tool in NETWORK_TOOLS:
        return f"{tool} is turned off for this agent. Ask the user for what the page says."
    if tool in FILE_TOOLS | SEARCH_TOOLS:
        hit = next((p for p in paths_in(tool_input) if SECRET_PATH.search(p)), None)
        if hit:
            return (
                f"{hit} is a secrets file. The agent doesn't read or change secrets; ask the "
                "user to supply the value it needs."
            )
    return None


def deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Blocked by agent guard: {reason}",
        }
    }


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input is not an object")
    except (ValueError, OSError):
        print(json.dumps(deny("The guard couldn't read this tool call, so it was blocked.")))
        return 0
    reason = decide(event)
    if reason is None:
        return 0
    with contextlib.suppress(OSError):  # a full disk must not turn a block into an allow
        _audit.record(event, "denied", reason)
    print(json.dumps(deny(reason)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
