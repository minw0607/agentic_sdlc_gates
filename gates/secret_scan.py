"""G4 secret scan: gitleaks CLI over the PR's commits, with the repo's .gitleaks.toml.

Uses the gitleaks CLI directly rather than gitleaks-action, which needs a license key on
organization-owned repos. Secrets are redacted in the report; only the rule, file, line
and commit are kept.

Environment: GATES_BASE_REF (base commit), GATES_HEAD_REF (default HEAD),
GATES_GITLEAKS_BIN (default ``gitleaks``), GATES_GITLEAKS_CONFIG (default ``.gitleaks.toml``;
the reusable workflow points it at the base commit's copy).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from gates.config import GatesConfig
from gates.report import CannotEvaluate, Finding, Outcome, Result, env, run_gate

CONFIG = ".gitleaks.toml"


def gitleaks_config() -> str:
    return os.environ.get("GATES_GITLEAKS_CONFIG") or CONFIG


def judge(leaks: list[dict[str, Any]]) -> Outcome:
    findings = [
        Finding(
            result=Result.FAIL,
            message=(
                f"{leak.get('Description') or leak.get('RuleID')} "
                f"(rule {leak.get('RuleID')}, commit {str(leak.get('Commit', ''))[:7]})"
            ),
            file=leak.get("File"),
            line=leak.get("StartLine"),
        )
        for leak in leaks
    ]
    if findings:
        where = ", ".join(sorted({f"{f.file}:{f.line}" for f in findings}))
        return Outcome(
            result=Result.FAIL,
            reason=f"{len(findings)} secret(s) found at {where}",
            findings=findings,
            details={"count": len(findings)},
        )
    return Outcome(result=Result.PASS, reason="No secrets in this PR's commits")


def run_gitleaks(base_ref: str, head_ref: str, gitleaks_bin: str) -> list[dict[str, Any]]:
    config = gitleaks_config()
    if not Path(config).exists():
        raise CannotEvaluate(f"{config} not found")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "leaks.json"
        cmd = [
            gitleaks_bin, "git", ".",
            "--log-opts", f"{base_ref}..{head_ref}",
            "--config", config,
            "--redact",
            "--no-banner",
            "--report-format", "json",
            "--report-path", str(out),
            "--exit-code", "0",
        ]  # fmt: skip
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise CannotEvaluate(f"gitleaks did not run: {e}") from e
        if res.returncode != 0 or not out.exists():
            raise CannotEvaluate(f"gitleaks exited {res.returncode}: {res.stderr.strip()[-300:]}")
        try:
            data: list[dict[str, Any]] = json.loads(out.read_text() or "[]")
        except json.JSONDecodeError as e:
            raise CannotEvaluate(f"gitleaks report was not JSON: {e}") from e
        return data


def gate(cfg: GatesConfig) -> Outcome:
    base_ref = env("GATES_BASE_REF")
    head_ref = os.environ.get("GATES_HEAD_REF", "HEAD")
    gitleaks_bin = os.environ.get("GATES_GITLEAKS_BIN", "gitleaks")
    return judge(run_gitleaks(base_ref, head_ref, gitleaks_bin))


def main() -> int:
    return run_gate("secret_scan", "G4", "Secret scan", gate)


if __name__ == "__main__":
    sys.exit(main())
