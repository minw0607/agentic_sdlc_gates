"""PreToolUse guard: block secret reads, outbound network calls, force pushes, package installs
and changes to the agent's own controls.

The permission deny rules in .claude/settings.json match tool calls by name and path. They don't
see a Bash command that opens the file itself (``python -c "open('.env')"``), so this hook
inspects every call, Bash included, before it runs.

A blocked call gets ``permissionDecision: "deny"`` with a plain-language reason that Claude Code
shows the agent and the user, and an audit log entry.

Claude Code lets a call through when a hook exits with an error, so the guard catches its own
failures (unreadable input, a bug, a missing ``_audit`` module) and denies instead. A hook that
runs past its timeout is still let through; that can't be fixed from inside the hook.

It's a pattern check, so a determined agent can get round it (for example by writing a script and
running it). It catches the obvious cases and explains why; blocking the network around the agent
is what actually stops data leaving. Stdlib only.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from typing import Any

try:
    import _audit
except Exception:  # checked in main(): without it the guard can't log, so it denies
    _audit = None  # type: ignore[assignment]

# Files an agent never needs to read: real env files, key material, cloud and SSH credentials.
# .env.example and .env.sample are templates with no values, so they stay readable.
SECRET_PATH = re.compile(
    r"\.env(?!\.(?:example|sample|template)\b)(?:\.[\w-]+)?(?!\w)"
    r"|(?:^|[/\s'\"])secrets?/"
    r"|\bid_(?:rsa|dsa|ecdsa|ed25519)\b|\.pem\b|\.p12\b"
    r"|\.ssh/|\.aws/|\.netrc\b|\.git-credentials\b",
    re.IGNORECASE,
)

# A shell glob that can expand to .env (".e*", ".en?", ".env*"), which the path pattern can't see.
SECRET_GLOB = re.compile(r"(?:^|[\s/'\"=])\.e(?:n(?:v)?)?[*?\[]")

# The agent's own controls and its audit log. The Read tool may look; nothing may change them.
CONTROL_PATH = re.compile(r"(?:^|/)\.claude/|(?:^|/)\.agent-audit(?:/|$)")
# In a shell line there's no telling a read from a write, so any mention is blocked.
CONTROL_IN_COMMAND = re.compile(r"\.claude\b|\.agent-audit\b")

# Programs that talk to the network, checked at each command position in a Bash line.
NETWORK_PROGRAMS = {
    "curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp", "ftp", "rsync",
    "socat", "http", "https", "xh", "aria2c", "dig", "nslookup", "host", "drill", "ping",
}  # fmt: skip

# git as a way out: a new or changed remote, or a push straight to a URL.
GIT_EGRESS = re.compile(
    r"\bgit\b[^;&|\n]*\bremote\s+(?:add|set-url)\b"
    r"|\bgit\b[^;&|\n]*\bpush\b[^;&|\n]*(?:https?://|ssh://|git://|file://|\S+@\S+:)"
)

# Installing a package by name skips the dependency guard (G2); `uv sync` of the lockfile doesn't.
PACKAGE_INSTALL = re.compile(
    r"\b(?:pip3?|pipx)\s+install\b|\bpython3?\s+-m\s+pip\s+install\b"
    r"|\buv\s+(?:add|pip\s+install|tool\s+install)\b"
)

# Network use from inside an interpreter or a one-liner.
NETWORK_CODE = re.compile(
    r"\b(requests|httpx|httpx2|aiohttp)\.(get|post|put|patch|delete|request|stream)\b"
    r"|\burllib\.request\b|\burlopen\(|\bhttp\.client\b|\bsocket\.(socket|create_connection)\b"
    r"|-m\s+http\.server\b|\bfetch\(\s*['\"]https?://|/dev/tcp/|Invoke-WebRequest|\biwr\b",
    re.IGNORECASE,
)

FORCE_PUSH = re.compile(
    r"\bgit\b[^;&|\n]*\bpush\b[^;&|\n]*(\s-[a-zA-Z]*f[a-zA-Z]*\b|\s--force(-with-lease)?\b|\s\+\S)"
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
    if CONTROL_IN_COMMAND.search(command):
        return (
            "This command touches the agent's own controls (.claude/) or its audit log "
            "(.agent-audit/). The agent doesn't change those; ask the user. To look at a "
            "setting, use the Read tool."
        )
    if SECRET_PATH.search(command) or SECRET_GLOB.search(command):
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
    if GIT_EGRESS.search(command):
        return (
            "Adding or changing a git remote, or pushing to a URL, can send the code somewhere "
            "else. Push to the existing origin, or ask the user."
        )
    if FORCE_PUSH.search(command):
        return "Force pushes rewrite shared history. Push normally, or ask the user to do it."
    if PACKAGE_INSTALL.search(command):
        return (
            "Installing a package by name skips the dependency guard. Add it to pyproject.toml "
            "for the user to review; CI checks it before anything installs it."
        )
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
    if tool in FILE_TOOLS - {"Read", "NotebookRead"}:
        hit = next((p for p in paths_in(tool_input) if CONTROL_PATH.search(p)), None)
        if hit:
            return (
                f"{hit} is part of the agent's own controls or audit log. The agent doesn't "
                "change those; ask the user."
            )
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
    try:
        if _audit is None:
            raise RuntimeError("the guard's _audit module is missing")
        reason = decide(event)
    except Exception as e:  # fail closed: a crashing hook would let the call through
        reason = f"The guard failed ({type(e).__name__}: {e}), so the call was blocked."
    if reason is None:
        return 0
    if _audit is not None:
        with contextlib.suppress(Exception):  # a full disk must not turn a block into an allow
            _audit.record(event, "denied", reason)
    print(json.dumps(deny(reason)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
