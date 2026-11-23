"""G2 on uv.lock: what actually gets installed, not just what pyproject.toml declares.

`uv sync --frozen` installs exactly what uv.lock says. A PR can add packages there that no one
declared (new dependencies of dependencies), point a package at a git repo or another index, or
swap a package's files while keeping its version. Each of those is checked here.
"""

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from gates import dep_guard
from gates.config import GatesConfig, load_config
from gates.dep_guard import LockChanges, PackageInfo, check, lock_changes, locked_packages
from gates.report import Result

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 19, tzinfo=UTC)
POPULAR = ["requests", "numpy", "httpx", "fastapi", "pydantic"]
OLD = PackageInfo(exists=True, first_release=NOW - timedelta(days=900))
PYPI = '{ registry = "https://pypi.org/simple" }'


def _pkg(name: str, version: str, source: str = PYPI, sha: str = "aa") -> str:
    return f"""
[[package]]
name = "{name}"
version = "{version}"
source = {source}
sdist = {{ url = "https://files.pythonhosted.org/packages/{name}.tar.gz", hash = "sha256:{sha}1" }}
wheels = [
    {{ url = "https://files.pythonhosted.org/packages/{name}.whl", hash = "sha256:{sha}2" }},
]
"""


PROJECT = """
version = 1
requires-python = ">=3.11"

[[package]]
name = "x"
version = "0.1.0"
source = { virtual = "." }
"""
BASE_LOCK = PROJECT + _pkg("fastapi", "0.120.0") + _pkg("starlette", "1.10.0")


def _cfg() -> GatesConfig:
    return load_config(ROOT / "gates.yaml")


def _pypi(**packages: PackageInfo) -> Any:
    return lambda name: packages.get(name, PackageInfo(exists=False))


# --- reading the lockfile ------------------------------------------------------------------


def test_locked_packages_reads_name_version_source_and_hashes() -> None:
    pkgs = {p.name: p for p in locked_packages(BASE_LOCK)}
    assert set(pkgs) == {"x", "fastapi", "starlette"}
    assert pkgs["fastapi"].version == "0.120.0"
    assert pkgs["fastapi"].source == {"registry": "https://pypi.org/simple"}
    assert pkgs["fastapi"].hashes == frozenset({"sha256:aa1", "sha256:aa2"})


def test_repo_shipped_lockfile_parses() -> None:
    pkgs = locked_packages((ROOT / "uv.lock").read_text())
    assert {"fastapi", "pydantic", "httpx2"} <= {p.name for p in pkgs}


# --- comparing base and head ---------------------------------------------------------------


def test_unchanged_lock_has_no_changes() -> None:
    changes = lock_changes(BASE_LOCK, BASE_LOCK)
    assert changes == LockChanges(new={}, findings=[])


def test_new_transitive_package_is_listed() -> None:
    changes = lock_changes(BASE_LOCK, BASE_LOCK + _pkg("anyio", "4.9.0"))
    assert changes.new == {"anyio": "4.9.0"}
    assert changes.findings == []


def test_upgrade_of_a_known_package_is_not_new() -> None:
    head = BASE_LOCK.replace('version = "1.10.0"', 'version = "1.11.0"')
    assert lock_changes(BASE_LOCK, head).new == {}


def test_swapped_files_for_the_same_version_fail() -> None:
    head = PROJECT + _pkg("fastapi", "0.120.0", sha="bb") + _pkg("starlette", "1.10.0")
    [f] = lock_changes(BASE_LOCK, head).findings
    assert f.result is Result.FAIL
    assert f.message == "fastapi 0.120.0: file hashes changed in uv.lock for the same version"


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ('{ git = "https://example.invalid/evil.git?rev=1#abc" }', "git"),
        ('{ url = "https://example.invalid/evil.tar.gz" }', "url"),
        ('{ registry = "https://pypi.example.invalid/simple" }', "registry"),
        ('{ path = "../vendor/evil" }', "path"),
    ],
)
def test_new_package_from_outside_pypi_fails(source: str, kind: str) -> None:
    changes = lock_changes(BASE_LOCK, BASE_LOCK + _pkg("helper", "1.0", source=source))
    [f] = changes.findings
    assert f.result is Result.FAIL
    assert f.message.startswith(f"helper: installs from {kind} ")
    assert f.file == "uv.lock"


def test_pypi_package_with_files_from_elsewhere_fails() -> None:
    head = BASE_LOCK.replace(
        "https://files.pythonhosted.org/packages/starlette.whl",
        "https://evil.example.invalid/s.whl",
    )
    [f] = lock_changes(BASE_LOCK, head).findings
    assert f.message == "starlette 1.10.0: downloads files from evil.example.invalid, not PyPI"


def test_extra_files_from_pypi_for_the_same_version_pass() -> None:
    # PyPI can publish more wheels for a release later; re-locking adds their hashes.
    extra = (
        '    { url = "https://files.pythonhosted.org/packages/s-arm.whl", hash = "sha256:cc" },\n'
    )
    marker = '    { url = "https://files.pythonhosted.org/packages/starlette.whl"'
    head = BASE_LOCK.replace(marker, extra + marker)
    assert lock_changes(BASE_LOCK, head).findings == []


def test_known_package_moved_to_another_index_fails() -> None:
    other = '{ registry = "https://pypi.example.invalid/simple" }'
    head = PROJECT + _pkg("fastapi", "0.120.0", source=other) + _pkg("starlette", "1.10.0")
    [f] = lock_changes(BASE_LOCK, head).findings
    assert "fastapi: installs from registry https://pypi.example.invalid/simple" in f.message


def test_source_already_on_base_is_not_reported_again() -> None:
    git = '{ git = "https://example.invalid/tool.git#abc" }'
    base = BASE_LOCK + _pkg("tool", "1.0", source=git)
    assert lock_changes(base, base).findings == []


def test_no_base_lock_treats_everything_as_new() -> None:
    assert lock_changes(None, BASE_LOCK).new == {"fastapi": "0.120.0", "starlette": "1.10.0"}


# --- the check with lockfile changes -------------------------------------------------------


def test_established_transitive_package_passes_without_approval() -> None:
    lock = LockChanges(new={"anyio": "4.9.0"}, findings=[])
    out = check({}, _cfg(), POPULAR, _pypi(anyio=OLD), NOW, lock=lock)
    assert out.result is Result.PASS
    assert out.reason == "1 new package(s) in uv.lock checked"
    assert out.details["new_dependencies"] == [
        {"name": "anyio", "spec": "4.9.0", "approved": 0, "via": "uv.lock", "age_days": 900}
    ]


def test_transitive_lookalike_fails() -> None:
    lock = LockChanges(new={"reqeusts": "1.0"}, findings=[])
    out = check({}, _cfg(), POPULAR, _pypi(reqeusts=OLD), NOW, lock=lock)
    assert out.result is Result.FAIL
    assert out.reason == "Blocked before install: reqeusts"
    assert "looks like `requests`" in out.findings[0].message


def test_transitive_package_missing_from_pypi_fails() -> None:
    lock = LockChanges(new={"ghostpkg": "1.0"}, findings=[])
    out = check({}, _cfg(), POPULAR, _pypi(), NOW, lock=lock)
    assert out.result is Result.FAIL
    assert "ghostpkg: not found on PyPI" in [f.message for f in out.findings]


def test_direct_dependency_is_not_checked_twice() -> None:
    lock = LockChanges(new={"uvicorn": "0.30.0"}, findings=[])
    out = check({"uvicorn": "uvicorn>=0.30"}, _cfg(), POPULAR, _pypi(uvicorn=OLD), NOW, lock=lock)
    assert [r["name"] for r in out.details["new_dependencies"]] == ["uvicorn"]
    assert "via" not in out.details["new_dependencies"][0]


def test_lock_findings_block() -> None:
    changes = lock_changes(BASE_LOCK, BASE_LOCK + _pkg("h", "1", source='{ url = "https://x" }'))
    out = check({}, _cfg(), POPULAR, _pypi(h=OLD), NOW, lock=changes)
    assert out.result is Result.FAIL
    assert out.reason == "Blocked before install: h"


# --- end to end ----------------------------------------------------------------------------

PYPROJECT = '[project]\nname = "x"\ndependencies = ["fastapi>=0.115"]\n'


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "pyproject.toml").write_text(PYPROJECT)
    (tmp_path / "uv.lock").write_text(BASE_LOCK)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GATES_BASE_REF", "main")
    return tmp_path


def test_gate_blocks_a_lockfile_only_change(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # pyproject.toml is untouched; only uv.lock gains a lookalike.
    (repo / "uv.lock").write_text(BASE_LOCK + _pkg("reqeusts", "2.0"))
    monkeypatch.setattr(dep_guard, "pypi_lookup", _pypi(reqeusts=OLD))
    out = dep_guard.gate(_cfg())
    assert out.result is Result.FAIL
    assert out.reason == "Blocked before install: reqeusts"


def test_gate_passes_an_unchanged_lock(repo: Path) -> None:
    assert dep_guard.gate(_cfg()).result is Result.PASS


def test_gate_warns_without_a_lockfile(repo: Path) -> None:
    (repo / "uv.lock").unlink()
    out = dep_guard.gate(_cfg())
    assert out.result is Result.WARN
    assert out.findings[0].message == "No uv.lock: only pyproject.toml was checked"
