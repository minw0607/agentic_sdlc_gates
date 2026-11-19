"""The one result format every gate writes, and the runner that enforces fail-closed.

Each gate is a function returning an ``Outcome``. ``run_gate`` wraps it:

- the gate's ``mode`` in gates.yaml is ``off``: report ``not_evaluated``, not blocking;
- the gate raises ``CannotEvaluate`` or any other exception: ``not_evaluated``, blocking;
- the gate finds a problem in ``warn`` mode: the result is downgraded to ``warn``;
- otherwise the gate's own result stands, and ``fail`` blocks.

The report lands in ``reports/<gate>.json``. The process exits 1 when the report blocks,
so the CI job goes red; the verdict job reads the reports, not the job colors.
"""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gates.config import GatesConfig, Mode, load_config

REPORTS_DIR = Path(os.environ.get("GATES_REPORTS_DIR", "reports"))


class Result(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    NOT_EVALUATED = "not_evaluated"


class Finding(BaseModel):
    result: Result
    message: str
    file: str | None = None
    line: int | None = None


class Outcome(BaseModel):
    """What a gate function returns."""

    result: Result
    reason: str
    findings: list[Finding] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class GateReport(Outcome):
    gate: str
    gate_id: str
    title: str
    mode: Mode
    blocking: bool


class CannotEvaluate(Exception):
    """The gate could not reach a verdict (missing input, outage). Never a pass."""


GateFn = Callable[[GatesConfig], Outcome]


def evaluate(gate: str, gate_id: str, title: str, fn: GateFn, cfg: GatesConfig) -> GateReport:
    mode = cfg.gates[gate].mode
    if mode is Mode.OFF:
        outcome = Outcome(result=Result.NOT_EVALUATED, reason="Turned off in gates.yaml")
    else:
        try:
            outcome = fn(cfg)
        except CannotEvaluate as e:
            outcome = Outcome(result=Result.NOT_EVALUATED, reason=f"Could not run: {e}")
        except Exception as e:
            traceback.print_exc()
            outcome = Outcome(
                result=Result.NOT_EVALUATED, reason=f"Gate crashed: {type(e).__name__}: {e}"
            )
    if mode is Mode.WARN and outcome.result is Result.FAIL:
        outcome = outcome.model_copy(
            update={"result": Result.WARN, "reason": f"{outcome.reason} (warn only)"}
        )
    blocking = mode is Mode.FAIL and outcome.result in (Result.FAIL, Result.NOT_EVALUATED)
    return GateReport(
        gate=gate,
        gate_id=gate_id,
        title=title,
        mode=mode,
        blocking=blocking,
        **outcome.model_dump(),
    )


def write_report(report: GateReport, reports_dir: Path | None = None) -> Path:
    reports_dir = reports_dir or REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report.gate}.json"
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def run_gate(gate: str, gate_id: str, title: str, fn: GateFn) -> int:
    """Entry point for a gate's ``main``. Returns the process exit code."""
    try:
        cfg = load_config()
    except Exception as e:
        # Without a valid policy no gate can run. Report it under the gate's own name.
        report = GateReport(
            gate=gate,
            gate_id=gate_id,
            title=title,
            mode=Mode.FAIL,
            blocking=True,
            result=Result.NOT_EVALUATED,
            reason=f"gates.yaml is missing or invalid: {e}",
        )
    else:
        report = evaluate(gate, gate_id, title, fn, cfg)
    write_report(report)
    print(f"{gate_id} {title}: {report.result.value} - {report.reason}")
    for f in report.findings:
        where = f" ({f.file}:{f.line})" if f.file else ""
        print(f"  [{f.result.value}] {f.message}{where}")
    return 1 if report.blocking else 0


def env(name: str) -> str:
    """A required environment variable, or CannotEvaluate."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise CannotEvaluate(f"environment variable {name} is not set")
    return value
