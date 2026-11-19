"""G3 known vulnerabilities: OSV-Scanner on uv.lock, failing only on vulnerabilities the PR adds.

Scans the PR's uv.lock and the base branch's uv.lock with the OSV-Scanner CLI and compares.
A vulnerability is identified by its alias set (CVE, GHSA, PYSEC ids) per package, so the
same advisory under a different id isn't counted as new. Vulnerabilities already on the
base branch are reported but don't block, so one old advisory doesn't stop every PR.

Environment: GATES_BASE_REF (base commit), GATES_OSV_BIN (default ``osv-scanner``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gates.config import GatesConfig
from gates.report import CannotEvaluate, Finding, Outcome, Result, env, run_gate

LOCKFILE = "uv.lock"


@dataclass(frozen=True)
class Vuln:
    package: str
    version: str
    ids: tuple[str, ...]
    aliases: frozenset[str]
    severity: str | None

    @property
    def label(self) -> str:
        return self.ids[0] if self.ids else sorted(self.aliases)[0]


def parse_osv(report: dict[str, Any]) -> list[Vuln]:
    """One entry per advisory group per package from OSV-Scanner's JSON output."""
    out: list[Vuln] = []
    for result in report.get("results") or []:
        for pkg in result.get("packages") or []:
            meta = pkg.get("package", {})
            for group in pkg.get("groups") or []:
                ids = tuple(group.get("ids") or ())
                aliases = frozenset(group.get("aliases") or ()) | frozenset(ids)
                out.append(
                    Vuln(
                        package=meta.get("name", "?"),
                        version=meta.get("version", "?"),
                        ids=ids,
                        aliases=aliases,
                        severity=group.get("max_severity") or None,
                    )
                )
    return out


def new_vulns(base: list[Vuln], head: list[Vuln]) -> list[Vuln]:
    known: dict[str, set[str]] = {}
    for v in base:
        known.setdefault(v.package, set()).update(v.aliases)
    return [v for v in head if not (v.aliases & known.get(v.package, set()))]


def scan(lockfile: Path, osv_bin: str) -> list[Vuln]:
    """Run OSV-Scanner on one lockfile. Exit 0 = clean, 1 = findings, else an error."""
    try:
        res = subprocess.run(
            [osv_bin, "scan", "source", "--lockfile", str(lockfile), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CannotEvaluate(f"osv-scanner did not run: {e}") from e
    if res.returncode not in (0, 1):
        raise CannotEvaluate(f"osv-scanner exited {res.returncode}: {res.stderr.strip()[-300:]}")
    try:
        return parse_osv(json.loads(res.stdout))
    except json.JSONDecodeError as e:
        raise CannotEvaluate(f"osv-scanner output was not JSON: {e}") from e


def base_lockfile(base_ref: str, into: Path) -> Path | None:
    res = subprocess.run(["git", "show", f"{base_ref}:{LOCKFILE}"], capture_output=True)
    if res.returncode != 0:
        stderr = res.stderr.decode(errors="replace")
        if "does not exist" in stderr or "exists on disk, but not in" in stderr:
            return None
        raise CannotEvaluate(f"could not read base {LOCKFILE}: {stderr.strip()}")
    path = into / LOCKFILE
    path.write_bytes(res.stdout)
    return path


def judge(base: list[Vuln], head: list[Vuln]) -> Outcome:
    added = new_vulns(base, head)
    existing = [v for v in head if v not in added]
    findings = [
        Finding(
            result=Result.FAIL,
            message=f"{v.package} {v.version}: {v.label}"
            + (f" (severity {v.severity})" if v.severity else ""),
            file=LOCKFILE,
        )
        for v in added
    ] + [
        Finding(
            result=Result.WARN,
            message=f"{v.package} {v.version}: {v.label} (already on base branch)",
            file=LOCKFILE,
        )
        for v in existing
    ]
    details = {"new": len(added), "existing": len(existing)}
    if added:
        pkgs = ", ".join(sorted({v.package for v in added}))
        return Outcome(
            result=Result.FAIL,
            reason=f"{len(added)} new known vulnerability(ies) in {pkgs}",
            findings=findings,
            details=details,
        )
    if existing:
        return Outcome(
            result=Result.WARN,
            reason=f"No new vulnerabilities; {len(existing)} already on the base branch",
            findings=findings,
            details=details,
        )
    return Outcome(result=Result.PASS, reason="No known vulnerabilities", details=details)


def gate(cfg: GatesConfig) -> Outcome:
    base_ref = env("GATES_BASE_REF")
    osv_bin = os.environ.get("GATES_OSV_BIN", "osv-scanner")
    head_lock = Path(LOCKFILE)
    if not head_lock.exists():
        raise CannotEvaluate(f"{LOCKFILE} not found")
    head = scan(head_lock, osv_bin)
    with tempfile.TemporaryDirectory() as tmp:
        base_path = base_lockfile(base_ref, Path(tmp))
        base = scan(base_path, osv_bin) if base_path else []
    return judge(base, head)


def main() -> int:
    return run_gate("osv", "G3", "Known vulnerabilities", gate)


if __name__ == "__main__":
    sys.exit(main())
