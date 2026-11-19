"""Tests for the acceptance-criteria plugin, run in an isolated pytest via pytester."""

import json

import pytest

CONFTEST = 'pytest_plugins = ["gates.pytest_ac"]\n'


def _run(pytester: pytest.Pytester, source: str) -> tuple[pytest.RunResult, dict]:  # type: ignore[type-arg]
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_sample=source)
    result = pytester.runpytest_inprocess("-p", "no:cacheprovider")
    path = pytester.path / "reports" / "ac_map.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return result, data


def test_records_criteria_and_outcomes(pytester: pytest.Pytester) -> None:
    result, data = _run(
        pytester,
        """
import pytest

@pytest.mark.ac("PARK-101/AC-1", "PARK-101/AC-2")
def test_a(): pass

@pytest.mark.ac("PARK-101/AC-2")
def test_b(): assert False

@pytest.mark.ac("PARK-101/AC-3")
@pytest.mark.skip(reason="later")
def test_c(): pass

def test_unmarked(): pass
""",
    )
    result.assert_outcomes(passed=2, failed=1, skipped=1)
    crit = data["criteria"]
    assert crit["PARK-101/AC-1"] == [{"nodeid": "test_sample.py::test_a", "outcome": "passed"}]
    assert {e["outcome"] for e in crit["PARK-101/AC-2"]} == {"passed", "failed"}
    assert crit["PARK-101/AC-3"][0]["outcome"] == "skipped"
    unmarked = next(t for t in data["tests"] if t["nodeid"].endswith("test_unmarked"))
    assert unmarked["criteria"] == []
    assert unmarked["outcome"] == "passed"


def test_failing_fixture_teardown_marks_test_failed(pytester: pytest.Pytester) -> None:
    _, data = _run(
        pytester,
        """
import pytest

@pytest.fixture
def broken():
    yield
    raise RuntimeError("teardown")

@pytest.mark.ac("PARK-101/AC-1")
def test_a(broken): pass
""",
    )
    assert data["criteria"]["PARK-101/AC-1"][0]["outcome"] == "failed"


def test_bad_criterion_id_is_a_usage_error(pytester: pytest.Pytester) -> None:
    result, _ = _run(
        pytester,
        """
import pytest

@pytest.mark.ac("AC-1")
def test_a(): pass
""",
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*bad acceptance criterion 'AC-1'*"])
