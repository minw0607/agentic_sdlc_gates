import json
from pathlib import Path
from typing import Any

import pytest

from gates import summary
from gates.config import GatesConfig, Mode, load_config
from gates.report import Finding, GateReport, Result, write_report

ROOT = Path(__file__).resolve().parent.parent


def _cfg(**modes: str) -> GatesConfig:
    raw = load_config(ROOT / "gates.yaml").model_dump()
    for gate in raw["gates"]:
        raw["gates"][gate] = {"mode": modes.get(gate, "fail")}
    return GatesConfig.model_validate(raw)


def _report(gate: str, result: Result, reason: str = "ok", **kw: Any) -> GateReport:
    gid, title = {g: (i, t) for g, i, t in summary.GATES}[gate]
    blocking = result in (Result.FAIL, Result.NOT_EVALUATED)
    return GateReport(
        gate=gate, gate_id=gid, title=title, mode=Mode.FAIL, blocking=blocking,
        result=result, reason=reason, **kw,
    )  # fmt: skip


def _write_all(tmp: Path, **overrides: GateReport) -> None:
    for gate, _, _ in summary.GATES:
        write_report(overrides.get(gate, _report(gate, Result.PASS)), tmp)


def test_all_pass_is_not_blocked(tmp_path: Path) -> None:
    _write_all(tmp_path)
    reports = summary.load_reports(_cfg(), tmp_path)
    assert not any(r.blocking for r in reports)
    assert "All required gates passed" in summary.render(reports, None, None)


def test_missing_report_blocks(tmp_path: Path) -> None:
    _write_all(tmp_path)
    (tmp_path / "tests.json").unlink()
    reports = summary.load_reports(_cfg(), tmp_path)
    tests = next(r for r in reports if r.gate == "tests")
    assert tests.result is Result.NOT_EVALUATED
    assert tests.blocking
    assert "Blocked** by G5 Tests and coverage" in summary.render(reports, None, None)


def test_missing_report_for_gate_turned_off_does_not_block(tmp_path: Path) -> None:
    _write_all(tmp_path)
    (tmp_path / "ticket_screen.json").unlink()
    reports = summary.load_reports(_cfg(ticket_screen="off"), tmp_path)
    g1 = reports[0]
    assert (g1.result, g1.blocking, g1.reason) == (
        Result.NOT_EVALUATED, False, "Turned off in gates.yaml"
    )  # fmt: skip


def test_unreadable_report_blocks(tmp_path: Path) -> None:
    _write_all(tmp_path)
    (tmp_path / "osv.json").write_text("{not json")
    osv = next(r for r in summary.load_reports(_cfg(), tmp_path) if r.gate == "osv")
    assert osv.blocking
    assert osv.reason == "Report is unreadable"


def test_render_lists_findings_and_escapes_cells() -> None:
    finding = Finding(result=Result.FAIL, message="key | in <b>file</b>", file="app/w.py", line=3)
    reports = [_report("secret_scan", Result.FAIL, "1 secret | found", findings=[finding])]
    md = summary.render(reports, "https://example.invalid/run/1", "abcdef1234")
    assert summary.MARKER in md
    assert "| G4 Secret scan | ❌ fail | 1 secret \\| found |" in md
    assert "- ❌ key \\| in &lt;b>file&lt;/b> (`app/w.py:3`)" in md
    assert "[details](https://example.invalid/run/1) · commit `abcdef1`" in md


def test_render_trace() -> None:
    details = {
        "ticket": {"key": "PARK-101", "summary": "Filter rides", "risk": "low"},
        "criteria": [
            {"id": "PARK-101/AC-1", "text": "Filters", "covered": True,
             "tests": [{"nodeid": "tests/t.py::test_a", "outcome": "passed"}]},
            {"id": "PARK-101/AC-2", "text": "Zero", "covered": False, "tests": []},
        ],
        "commits": [{"sha": "a" * 40, "subject": "Add filter", "tickets": ["PARK-101"],
                     "agent_session": "sess-1"}],
    }  # fmt: skip
    md = summary.render([_report("traceability", Result.FAIL, "gap", details=details)], None, None)
    assert "**PARK-101: Filter rides** · risk **low**" in md
    assert "| **AC-1** Filters | `test_a` passed | ✅ |" in md
    assert "| **AC-2** Zero | none | ❌ |" in md
    assert "| `aaaaaaa` Add filter | PARK-101 | `sess-1` |" in md


def test_main_writes_evidence_and_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports_dir = tmp_path / "reports"
    _write_all(reports_dir, dep_guard=_report("dep_guard", Result.FAIL, "Blocked before install"))
    step = tmp_path / "step.md"
    monkeypatch.setattr(summary, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(summary, "load_config", lambda: _cfg())
    for var in ("GITHUB_TOKEN", "GATES_PR_NUMBER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    assert summary.main() == 1
    ev = json.loads((reports_dir / "evidence.json").read_text())
    assert ev["verdict"] == "blocked"
    assert ev["run_url"] == "https://github.com/o/r/actions/runs/42"
    assert "Blocked** by G2 Dependency guard" in step.read_text()


def test_upsert_comment_updates_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, url: str, token: str, body: Any = None) -> Any:
        calls.append((method, url))
        if method == "GET":
            return [{"id": 1, "body": "hi"}, {"id": 7, "body": f"{summary.MARKER}\nold"}]
        return {}

    monkeypatch.setattr(summary, "_api", fake_api)
    assert summary.upsert_comment("o/r", "5", "t", "new", "https://api") == "updated"
    assert calls[-1] == ("PATCH", "https://api/repos/o/r/issues/comments/7")


def test_upsert_comment_creates_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_api(method: str, url: str, token: str, body: Any = None) -> Any:
        calls.append((method, url))
        return [] if method == "GET" else {}

    monkeypatch.setattr(summary, "_api", fake_api)
    assert summary.upsert_comment("o/r", "5", "t", "new", "https://api") == "created"
    assert calls[-1] == ("POST", "https://api/repos/o/r/issues/5/comments")
