"""G5 tests and coverage: run pytest with coverage, fail on any failing test or a low floor.

The coverage floor and the measured source folders come from gates.yaml. pytest also
writes reports/ac_map.json (via gates/pytest_ac.py), which traceability (G6) uses.

Runs only after the dependency guard passed, because it installs the PR's dependencies.
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from gates.config import GatesConfig
from gates.report import CannotEvaluate, Finding, Outcome, Result, run_gate

JUNIT = Path("reports/junit.xml")
COVERAGE = Path("reports/coverage.json")


def failed_tests(junit_xml: str) -> list[str]:
    root = ET.fromstring(junit_xml)
    out = []
    for case in root.iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            out.append(f"{case.get('classname')}::{case.get('name')}")
    return out


def counts(junit_xml: str) -> dict[str, int]:
    root = ET.fromstring(junit_xml)
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    keys = ("tests", "failures", "errors", "skipped")
    return {k: sum(int(s.get(k, 0)) for s in suites) for k in keys}


def judge(junit_xml: str, coverage_pct: float, floor: float, pytest_exit: int) -> Outcome:
    c = counts(junit_xml)
    failed = failed_tests(junit_xml)
    findings = [Finding(result=Result.FAIL, message=f"Failed: {t}") for t in failed]
    passed = c["tests"] - c["failures"] - c["errors"] - c["skipped"]
    details = {**c, "passed": passed, "coverage": round(coverage_pct, 1), "floor": floor}
    problems = []
    if failed or pytest_exit not in (0,):
        problems.append(f"{len(failed) or 'some'} failing test(s)")
    if c["tests"] == 0:
        problems.append("no tests ran")
    if coverage_pct < floor:
        problems.append(f"coverage {coverage_pct:.1f}% is below the {floor:g}% floor")
        findings.append(
            Finding(result=Result.FAIL, message=f"Coverage {coverage_pct:.1f}% < {floor:g}%")
        )
    if problems:
        return Outcome(
            result=Result.FAIL, reason="; ".join(problems), findings=findings, details=details
        )
    return Outcome(
        result=Result.PASS,
        reason=f"{passed} passed, coverage {coverage_pct:.1f}% (floor {floor:g}%)",
        details=details,
    )


def gate(cfg: GatesConfig) -> Outcome:
    JUNIT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", f"--junitxml={JUNIT}"]
    cmd += [f"--cov={s}" for s in cfg.coverage.source]
    cmd += [f"--cov-report=json:{COVERAGE}", "--cov-report=term"]
    res = subprocess.run(cmd)
    if res.returncode not in (0, 1) or not JUNIT.exists() or not COVERAGE.exists():
        raise CannotEvaluate(f"pytest exited {res.returncode} without complete results")
    pct = float(json.loads(COVERAGE.read_text())["totals"]["percent_covered"])
    return judge(JUNIT.read_text(), pct, cfg.coverage.floor, res.returncode)


def main() -> int:
    return run_gate("tests", "G5", "Tests and coverage", gate)


if __name__ == "__main__":
    sys.exit(main())
