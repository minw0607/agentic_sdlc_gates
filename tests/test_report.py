import json
from pathlib import Path

import pytest

from gates.config import GatesConfig, Mode, load_config
from gates.report import (
    CannotEvaluate,
    Finding,
    Outcome,
    Result,
    evaluate,
    run_gate,
    write_report,
)

ROOT = Path(__file__).resolve().parent.parent


def _cfg(mode: str = "fail") -> GatesConfig:
    raw = load_config(ROOT / "gates.yaml").model_dump()
    raw["gates"]["tests"] = {"mode": mode}
    return GatesConfig.model_validate(raw)


def _fail(_: GatesConfig) -> Outcome:
    return Outcome(
        result=Result.FAIL, reason="bad", findings=[Finding(result=Result.FAIL, message="x")]
    )


def test_pass_does_not_block() -> None:
    report = evaluate(
        "tests", "G5", "T", lambda _: Outcome(result=Result.PASS, reason="ok"), _cfg()
    )
    assert report.result is Result.PASS
    assert not report.blocking


def test_fail_blocks_in_fail_mode() -> None:
    report = evaluate("tests", "G5", "T", _fail, _cfg())
    assert report.result is Result.FAIL
    assert report.blocking


def test_warn_mode_downgrades_fail() -> None:
    report = evaluate("tests", "G5", "T", _fail, _cfg("warn"))
    assert report.result is Result.WARN
    assert "warn only" in report.reason
    assert not report.blocking


def test_off_mode_is_not_evaluated_and_does_not_block() -> None:
    report = evaluate("tests", "G5", "T", _fail, _cfg("off"))
    assert report.result is Result.NOT_EVALUATED
    assert report.mode is Mode.OFF
    assert not report.blocking


def test_cannot_evaluate_is_never_a_pass() -> None:
    def fn(_: GatesConfig) -> Outcome:
        raise CannotEvaluate("PyPI unreachable")

    report = evaluate("tests", "G5", "T", fn, _cfg())
    assert report.result is Result.NOT_EVALUATED
    assert report.blocking
    assert "PyPI unreachable" in report.reason


def test_crash_is_not_evaluated_and_blocks() -> None:
    def fn(_: GatesConfig) -> Outcome:
        raise KeyError("boom")

    report = evaluate("tests", "G5", "T", fn, _cfg())
    assert report.result is Result.NOT_EVALUATED
    assert report.blocking
    assert "KeyError" in report.reason


def test_write_report_round_trips(tmp_path: Path) -> None:
    report = evaluate("tests", "G5", "T", _fail, _cfg())
    path = write_report(report, tmp_path)
    data = json.loads(path.read_text())
    assert path.name == "tests.json"
    assert data["result"] == "fail"
    assert data["findings"][0]["message"] == "x"


def test_run_gate_with_invalid_policy_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "gates.yaml").write_text("version: 1\n")
    monkeypatch.setattr("gates.report.REPORTS_DIR", tmp_path / "reports")
    code = run_gate("tests", "G5", "T", _fail)
    data = json.loads((tmp_path / "reports" / "tests.json").read_text())
    assert code == 1
    assert data["result"] == "not_evaluated"
    assert "gates.yaml" in data["reason"]
