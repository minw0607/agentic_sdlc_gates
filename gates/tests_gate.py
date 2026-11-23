"""G5 tests and coverage: fail on any failing test or coverage below the floor.

The coverage floor and the measured source folders come from gates.yaml. pytest also writes
ac_map.json (via gates/pytest_ac.py), which traceability (G6) uses.

Three ways to run it:

- ``python -m gates.tests_gate``: run pytest here, then judge. Used by this repo's own workflow.
- ``python -m gates.tests_gate args``: print the pytest coverage arguments from policy.
- ``python -m gates.tests_gate judge``: judge results another job produced (``junit.xml``,
  ``coverage.json`` and ``pytest_exit`` in GATES_RAW_DIR) without running anything. The
  reusable workflow runs the PR's tests in one job and judges them here, in a job that never
  executes the PR's code, so that code can't write its own gate report.

Raw results live in GATES_RAW_DIR, default reports/. Runs only after the dependency guard
passed, because running the tests installs the PR's dependencies.
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from gates.config import GatesConfig, load_config, raw_dir
from gates.report import CannotEvaluate, Finding, Outcome, Result, run_gate


def raw_files() -> tuple[Path, Path, Path]:
    """junit.xml, coverage.json and pytest_exit in the raw results folder."""
    d = raw_dir()
    return d / "junit.xml", d / "coverage.json", d / "pytest_exit"


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


def pytest_args(cfg: GatesConfig) -> list[str]:
    return [f"--cov={src}" for src in cfg.coverage.source]


def judge_files(cfg: GatesConfig, pytest_exit: int) -> Outcome:
    junit, coverage, _ = raw_files()
    if pytest_exit not in (0, 1) or not junit.exists() or not coverage.exists():
        raise CannotEvaluate(f"pytest exited {pytest_exit} without complete results")
    try:
        pct = float(json.loads(coverage.read_text())["totals"]["percent_covered"])
    except (ValueError, KeyError, TypeError) as e:
        raise CannotEvaluate(f"{coverage.name} is unreadable: {e}") from e
    return judge(junit.read_text(), pct, cfg.coverage.floor, pytest_exit)


def gate(cfg: GatesConfig) -> Outcome:
    """Run pytest with coverage here, then judge."""
    junit, coverage, _ = raw_files()
    junit.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", f"--junitxml={junit}", *pytest_args(cfg)]
    cmd += [f"--cov-report=json:{coverage}", "--cov-report=term"]
    res = subprocess.run(cmd)
    return judge_files(cfg, res.returncode)


def judge_raw(cfg: GatesConfig) -> Outcome:
    """Judge results another job produced. Runs nothing."""
    _, _, exit_file = raw_files()
    if not exit_file.exists():
        raise CannotEvaluate(f"raw test results not found in {exit_file.parent}/")
    try:
        code = int(exit_file.read_text().strip())
    except ValueError as e:
        raise CannotEvaluate(f"{exit_file.name} is unreadable: {e}") from e
    return judge_files(cfg, code)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["args"]:
        print(" ".join(pytest_args(load_config())))
        return 0
    if args == ["judge"]:
        return run_gate("tests", "G5", "Tests and coverage", judge_raw)
    if args:
        print("usage: python -m gates.tests_gate [args|judge]", file=sys.stderr)
        return 2
    return run_gate("tests", "G5", "Tests and coverage", gate)


if __name__ == "__main__":
    sys.exit(main())
