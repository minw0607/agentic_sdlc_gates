"""Pytest plugin: record which acceptance criteria each test covers, and its outcome.

Tests declare coverage with ``@pytest.mark.ac("PARK-101/AC-1")``. At the end of the
session the plugin writes ``reports/ac_map.json``, which ``gates/traceability.py`` joins
to the ticket. Load it with ``pytest_plugins = ["gates.pytest_ac"]`` in a conftest.

A test's outcome is ``passed`` only if setup, call and teardown all passed. A skipped
test counts as ``skipped``, which traceability treats as not covering the criterion.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

CRITERION_ID = re.compile(r"^[A-Z][A-Z0-9]*-\d+/AC-\d+$")
DEFAULT_PATH = "reports/ac_map.json"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("ac_map_path", "Where to write the criteria map", default=DEFAULT_PATH)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", 'ac(*criteria): acceptance criteria this test covers, e.g. ac("PARK-101/AC-1")'
    )
    # One recorder per pytest session, so nested sessions (pytester) don't share state.
    config.pluginmanager.register(AcRecorder(config), "ac_recorder")


class AcRecorder:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.criteria: dict[str, list[str]] = {}
        self.outcomes: dict[str, str] = {}

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            ids: list[str] = []
            for mark in item.iter_markers(name="ac"):
                for arg in mark.args:
                    if not isinstance(arg, str) or not CRITERION_ID.match(arg):
                        raise pytest.UsageError(
                            f"{item.nodeid}: bad acceptance criterion {arg!r}; "
                            'expected a string like "PARK-101/AC-1"'
                        )
                    ids.append(arg)
            self.criteria[item.nodeid] = sorted(set(ids))

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        current = self.outcomes.get(report.nodeid)
        if report.failed:
            self.outcomes[report.nodeid] = "failed"
        elif report.skipped:
            if current != "failed":
                self.outcomes[report.nodeid] = "skipped"
        elif report.when == "call" and current is None:
            self.outcomes[report.nodeid] = "passed"

    def build_map(self) -> dict[str, Any]:
        tests: list[dict[str, Any]] = [
            {"nodeid": nodeid, "criteria": crit, "outcome": self.outcomes.get(nodeid, "not_run")}
            for nodeid, crit in sorted(self.criteria.items())
        ]
        by_criterion: dict[str, list[dict[str, str]]] = {}
        for t in tests:
            for c in t["criteria"]:
                entry = {"nodeid": t["nodeid"], "outcome": t["outcome"]}
                by_criterion.setdefault(c, []).append(entry)
        return {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "criteria": dict(sorted(by_criterion.items())),
            "tests": tests,
        }

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        if hasattr(self.config, "workerinput"):  # pytest-xdist worker: controller writes
            return
        path = Path(self.config.rootpath, self.config.getini("ac_map_path"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.build_map(), indent=2) + "\n", encoding="utf-8")
