import io
import json
import subprocess
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from gates import dep_guard
from gates.config import GatesConfig, load_config
from gates.dep_guard import (
    PackageInfo,
    check,
    closest_popular,
    declared_dependencies,
    edit_distance,
    new_dependencies,
)
from gates.report import CannotEvaluate, Result

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 19, tzinfo=UTC)
POPULAR = ["requests", "numpy", "pandas", "httpx", "rich", "fastapi", "pydantic"]

BASE = """
[project]
name = "x"
dependencies = ["fastapi>=0.115", "pydantic>=2.8"]
[dependency-groups]
dev = ["pytest>=8", {include-group = "lint"}]
lint = ["ruff"]
"""


def _cfg(**dep_guard: Any) -> GatesConfig:
    raw = load_config(ROOT / "gates.yaml").model_dump()
    raw["dep_guard"].update(dep_guard)
    return GatesConfig.model_validate(raw)


def _pypi(**packages: PackageInfo) -> Any:
    def lookup(name: str) -> PackageInfo:
        return packages.get(name, PackageInfo(exists=False))

    return lookup


OLD = PackageInfo(exists=True, first_release=NOW - timedelta(days=900))


# --- parsing -------------------------------------------------------------------------------


def test_declared_dependencies_covers_project_and_groups() -> None:
    deps = declared_dependencies(BASE)
    assert set(deps) == {"fastapi", "pydantic", "pytest", "ruff"}
    assert deps["fastapi"] == "fastapi>=0.115"


def test_declared_dependencies_normalizes_and_handles_extras_and_markers() -> None:
    text = """
[project]
dependencies = ["Py_YAML[libyaml]>=6 ; python_version>'3.8'", "uvicorn"]
[project.optional-dependencies]
docs = ["mkdocs"]
"""
    assert set(declared_dependencies(text)) == {"py-yaml", "uvicorn", "mkdocs"}


def test_new_dependencies_only_lists_additions() -> None:
    head = BASE.replace('"pydantic>=2.8"', '"pydantic>=2.9", "queueline-sdk>=1.0"')
    assert new_dependencies(BASE, head) == {"queueline-sdk": "queueline-sdk>=1.0"}


def test_new_dependencies_without_base_treats_all_as_new() -> None:
    assert set(new_dependencies(None, BASE)) == {"fastapi", "pydantic", "pytest", "ruff"}


# --- lookalikes ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "d"),
    [("requests", "requests", 0), ("reqeusts", "requests", 1), ("requets", "requests", 1),
     ("requestss", "requests", 1), ("rquests", "requests", 1), ("reqests2", "requests", 2),
     ("numpy", "pandas", 6), ("", "abc", 3)],
)  # fmt: skip
def test_edit_distance(a: str, b: str, d: int) -> None:
    assert edit_distance(a, b) == d


def test_closest_popular_flags_one_letter_lookalike() -> None:
    assert closest_popular("reqeusts", POPULAR, 2, 5) == ("requests", 1)


def test_closest_popular_ignores_the_real_package() -> None:
    assert closest_popular("requests", POPULAR, 2, 5) is None


def test_closest_popular_skips_short_names() -> None:
    assert closest_popular("rick", POPULAR, 2, 5) is None  # 1 edit from `rich`


def test_closest_popular_ignores_distant_names() -> None:
    assert closest_popular("queueline-sdk", POPULAR, 2, 5) is None


def test_load_popular_skips_comments(tmp_path: Path) -> None:
    f = tmp_path / "top.txt"
    f.write_text("# header\nRequests\n\nPy_YAML\n")
    assert dep_guard.load_popular(f) == ["requests", "py-yaml"]


def test_load_popular_missing_file_cannot_evaluate(tmp_path: Path) -> None:
    with pytest.raises(CannotEvaluate):
        dep_guard.load_popular(tmp_path / "nope.txt")


def test_shipped_popular_list_has_requests() -> None:
    names = dep_guard.load_popular(ROOT / "gates" / "data" / "top_pypi.txt")
    assert len(names) == 1000
    assert "requests" in names


# --- the check -----------------------------------------------------------------------------


def test_no_new_dependencies_passes() -> None:
    out = check({}, _cfg(), POPULAR, _pypi(), NOW)
    assert out.result is Result.PASS
    assert out.reason == "No new dependencies"


def test_approved_established_package_passes() -> None:
    out = check({"fastapi": "fastapi"}, _cfg(), POPULAR, _pypi(fastapi=OLD), NOW)
    assert out.result is Result.PASS
    assert out.findings == []


def test_package_missing_from_pypi_fails() -> None:
    out = check({"queueline-sdk": "queueline-sdk"}, _cfg(), POPULAR, _pypi(), NOW)
    assert out.result is Result.FAIL
    assert "queueline-sdk: not found on PyPI" in [f.message for f in out.findings]


def test_lookalike_fails_even_if_it_exists() -> None:
    out = check({"reqeusts": "reqeusts"}, _cfg(), POPULAR, _pypi(reqeusts=OLD), NOW)
    assert out.result is Result.FAIL
    assert any("looks like `requests`" in f.message for f in out.findings)
    assert out.details["new_dependencies"][0]["looks_like"] == "requests"


def test_new_package_fails_age_check() -> None:
    fresh = PackageInfo(exists=True, first_release=NOW - timedelta(days=3))
    out = check(
        {"brand-new-lib": "brand-new-lib"}, _cfg(), POPULAR, _pypi(**{"brand-new-lib": fresh}), NOW
    )
    assert out.result is Result.FAIL
    assert any("first released 3 day(s) ago" in f.message for f in out.findings)


def test_package_without_files_fails() -> None:
    empty = PackageInfo(exists=True, first_release=None)
    out = check({"ghost-lib": "ghost-lib"}, _cfg(), POPULAR, _pypi(**{"ghost-lib": empty}), NOW)
    assert out.result is Result.FAIL


def test_unapproved_established_package_warns_by_default() -> None:
    out = check({"tabulate": "tabulate"}, _cfg(), POPULAR, _pypi(tabulate=OLD), NOW)
    assert out.result is Result.WARN
    assert out.findings[0].message == "tabulate: not on approved_packages in gates.yaml"


def test_unapproved_can_be_made_blocking() -> None:
    out = check(
        {"tabulate": "tabulate"}, _cfg(unapproved="fail"), POPULAR, _pypi(tabulate=OLD), NOW
    )
    assert out.result is Result.FAIL


def test_unapproved_check_can_be_turned_off() -> None:
    out = check({"tabulate": "tabulate"}, _cfg(unapproved="off"), POPULAR, _pypi(tabulate=OLD), NOW)
    assert out.result is Result.PASS


def test_approved_package_skips_lookalike_check() -> None:
    # httpx2 is one edit from httpx but is approved after review.
    out = check({"httpx2": "httpx2"}, _cfg(), POPULAR, _pypi(httpx2=OLD), NOW)
    assert out.result is Result.PASS


def test_s3_scenario_blocks_both_packages() -> None:
    new = {"queueline-sdk": "queueline-sdk>=1.0", "reqeusts": "reqeusts>=2.31"}
    out = check(new, _cfg(), POPULAR, _pypi(), NOW)
    assert out.result is Result.FAIL
    assert out.reason == "Blocked before install: queueline-sdk, reqeusts"


# --- PyPI client (network mocked) ----------------------------------------------------------


class _Resp(io.BytesIO):
    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: object) -> None:
        pass


def test_pypi_lookup_reads_first_release(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "releases": {
            "1.0": [{"upload_time_iso_8601": "2020-01-02T03:04:05.000000Z"}],
            "0.1": [{"upload_time_iso_8601": "2019-05-06T00:00:00.000000Z"}],
            "0.0": [],
        }
    }
    monkeypatch.setattr(
        dep_guard.urllib.request, "urlopen", lambda *a, **k: _Resp(json.dumps(body).encode())
    )
    info = dep_guard.pypi_lookup("x")
    assert info.exists
    assert info.first_release == datetime(2019, 5, 6, tzinfo=UTC)


def test_pypi_lookup_404_means_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_404(*a: object, **k: object) -> None:
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(dep_guard.urllib.request, "urlopen", raise_404)
    assert dep_guard.pypi_lookup("x") == PackageInfo(exists=False)


def test_pypi_outage_cannot_evaluate(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def down(*a: object, **k: object) -> None:
        calls.append(1)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(dep_guard.urllib.request, "urlopen", down)
    with pytest.raises(CannotEvaluate, match="connection refused"):
        dep_guard.pypi_lookup("x")
    assert len(calls) == 3


def test_pypi_server_error_cannot_evaluate(monkeypatch: pytest.MonkeyPatch) -> None:
    def err(*a: object, **k: object) -> None:
        raise urllib.error.HTTPError("u", 503, "Unavailable", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(dep_guard.urllib.request, "urlopen", err)
    with pytest.raises(CannotEvaluate):
        dep_guard.pypi_lookup("x")


# --- end to end against a temporary git repo -----------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_gate_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pyproject.toml").write_text(BASE)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "pyproject.toml").write_text(
        BASE.replace('"pydantic>=2.8"', '"pydantic", "reqeusts"')
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GATES_BASE_REF", "main")
    monkeypatch.setattr(dep_guard, "pypi_lookup", _pypi())
    cfg = _cfg(popular_names=str(ROOT / "gates" / "data" / "top_pypi.txt"))
    out = dep_guard.gate(cfg)
    assert out.result is Result.FAIL
    assert [r["name"] for r in out.details["new_dependencies"]] == ["reqeusts"]


def test_base_pyproject_missing_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "README").write_text("x")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.chdir(tmp_path)
    assert dep_guard.base_pyproject("main") is None
    with pytest.raises(CannotEvaluate):
        dep_guard.base_pyproject("no-such-ref")
