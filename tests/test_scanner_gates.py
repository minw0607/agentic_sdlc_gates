"""Unit tests for the wrappers around OSV-Scanner (G3), gitleaks (G4) and pytest (G5)."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gates import osv_gate, secret_scan, tests_gate
from gates.report import CannotEvaluate, Result


def _osv_report(*pkgs: tuple[str, str, list[str], list[str]]) -> dict[str, Any]:
    return {
        "results": [
            {
                "source": {"path": "uv.lock", "type": "lockfile"},
                "packages": [
                    {
                        "package": {"name": n, "version": v, "ecosystem": "PyPI"},
                        "groups": [{"ids": ids, "aliases": aliases, "max_severity": "7.5"}],
                        "vulnerabilities": [{"id": i} for i in ids],
                    }
                    for n, v, ids, aliases in pkgs
                ],
            }
        ]
    }


REQ = ("requests", "2.19.0", ["PYSEC-2018-28"], ["CVE-2018-18074", "GHSA-x84v-xcm2-53pg"])
URL = ("urllib3", "1.0", ["GHSA-aaaa"], ["CVE-2020-1"])


# --- G3 OSV --------------------------------------------------------------------------------


def test_parse_osv_reads_groups() -> None:
    [v] = osv_gate.parse_osv(_osv_report(REQ))
    assert (v.package, v.version, v.label, v.severity) == (
        "requests",
        "2.19.0",
        "PYSEC-2018-28",
        "7.5",
    )
    assert "CVE-2018-18074" in v.aliases


def test_parse_osv_handles_empty_report() -> None:
    assert osv_gate.parse_osv({"results": []}) == []
    assert osv_gate.parse_osv({}) == []


def test_osv_clean_passes() -> None:
    assert osv_gate.judge([], []).result is Result.PASS


def test_osv_new_vulnerability_fails() -> None:
    out = osv_gate.judge([], osv_gate.parse_osv(_osv_report(REQ)))
    assert out.result is Result.FAIL
    assert "requests" in out.reason


def test_osv_existing_vulnerability_only_warns() -> None:
    base = osv_gate.parse_osv(_osv_report(REQ))
    # Same advisory, reported under a different primary id on the head branch.
    head = osv_gate.parse_osv(_osv_report(("requests", "2.19.0", ["GHSA-x84v-xcm2-53pg"], [])))
    out = osv_gate.judge(base, head)
    assert out.result is Result.WARN
    assert out.details == {"new": 0, "existing": 1}


def test_osv_only_new_ones_block() -> None:
    base = osv_gate.parse_osv(_osv_report(REQ))
    head = osv_gate.parse_osv(_osv_report(REQ, URL))
    out = osv_gate.judge(base, head)
    assert out.result is Result.FAIL
    assert out.details == {"new": 1, "existing": 1}


def _completed(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_osv_scan_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        osv_gate.subprocess, "run", lambda *a, **k: _completed(1, json.dumps(_osv_report(REQ)))
    )
    assert len(osv_gate.scan(Path("uv.lock"), "osv")) == 1
    monkeypatch.setattr(osv_gate.subprocess, "run", lambda *a, **k: _completed(127, "", "boom"))
    with pytest.raises(CannotEvaluate, match="exited 127"):
        osv_gate.scan(Path("uv.lock"), "osv")
    monkeypatch.setattr(osv_gate.subprocess, "run", lambda *a, **k: _completed(0, "not json"))
    with pytest.raises(CannotEvaluate, match="not JSON"):
        osv_gate.scan(Path("uv.lock"), "osv")


def test_osv_missing_binary_cannot_evaluate() -> None:
    with pytest.raises(CannotEvaluate, match="did not run"):
        osv_gate.scan(Path("uv.lock"), "/no/such/osv-scanner")


# --- G4 gitleaks ---------------------------------------------------------------------------

LEAK = {
    "RuleID": "parkwx-api-key",
    "Description": "Weather vendor API key",
    "File": "app/weather.py",
    "StartLine": 3,
    "Commit": "d775cf6a1b2c",
    "Secret": "REDACTED",
}


def test_secret_scan_clean_passes() -> None:
    assert secret_scan.judge([]).result is Result.PASS


def test_secret_scan_finding_fails_with_file_and_line() -> None:
    out = secret_scan.judge([LEAK])
    assert out.result is Result.FAIL
    assert out.reason == "1 secret(s) found at app/weather.py:3"
    f = out.findings[0]
    assert (f.file, f.line) == ("app/weather.py", 3)
    assert "d775cf6" in f.message
    assert "REDACTED" not in f.message


def test_gitleaks_failure_cannot_evaluate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(CannotEvaluate, match="not found"):
        secret_scan.run_gitleaks("main", "HEAD", "gitleaks")
    (tmp_path / ".gitleaks.toml").write_text("")
    with pytest.raises(CannotEvaluate, match="did not run"):
        secret_scan.run_gitleaks("main", "HEAD", "/no/such/gitleaks")
    monkeypatch.setattr(secret_scan.subprocess, "run", lambda *a, **k: _completed(2, "", "bad"))
    with pytest.raises(CannotEvaluate, match="exited 2"):
        secret_scan.run_gitleaks("main", "HEAD", "gitleaks")


def test_gitleaks_report_is_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitleaks.toml").write_text("")

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert "--redact" in cmd
        assert cmd[cmd.index("--log-opts") + 1] == "main..HEAD"
        Path(cmd[cmd.index("--report-path") + 1]).write_text(json.dumps([LEAK]))
        return _completed(0)

    monkeypatch.setattr(secret_scan.subprocess, "run", fake_run)
    assert secret_scan.run_gitleaks("main", "HEAD", "gitleaks") == [LEAK]


# --- G5 tests and coverage -----------------------------------------------------------------

JUNIT_OK = """<?xml version="1.0"?>
<testsuites><testsuite tests="3" failures="0" errors="0" skipped="1">
<testcase classname="tests.test_a" name="test_1"/>
<testcase classname="tests.test_a" name="test_2"/>
<testcase classname="tests.test_a" name="test_3"><skipped/></testcase>
</testsuite></testsuites>"""

JUNIT_FAIL = """<?xml version="1.0"?>
<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0">
<testcase classname="tests.test_a" name="test_1"/>
<testcase classname="tests.test_a" name="test_2"><failure message="x"/></testcase>
</testsuite></testsuites>"""


def test_tests_gate_passes() -> None:
    out = tests_gate.judge(JUNIT_OK, 91.2, 80, 0)
    assert out.result is Result.PASS
    assert out.reason == "2 passed, coverage 91.2% (floor 80%)"
    assert out.details["skipped"] == 1


def test_tests_gate_fails_on_failing_test() -> None:
    out = tests_gate.judge(JUNIT_FAIL, 95, 80, 1)
    assert out.result is Result.FAIL
    assert out.findings[0].message == "Failed: tests.test_a::test_2"


def test_tests_gate_fails_below_floor() -> None:
    out = tests_gate.judge(JUNIT_OK, 72.4, 80, 0)
    assert out.result is Result.FAIL
    assert "coverage 72.4% is below the 80% floor" in out.reason


def test_tests_gate_fails_when_no_tests_ran() -> None:
    empty = '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>'
    assert tests_gate.judge(empty, 100, 80, 0).result is Result.FAIL


def test_tests_gate_pytest_crash_cannot_evaluate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gates.config import load_config

    cfg = load_config()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tests_gate.subprocess, "run", lambda *a, **k: _completed(4))
    with pytest.raises(CannotEvaluate, match="pytest exited 4"):
        tests_gate.gate(cfg)
