"""The reusable workflow (.github/workflows/gates.yml) and the gate options it relies on.

In that workflow the gate code is a trusted checkout of this repo, the repo under review is
data in target/, and policy comes from target's base commit. These tests check that the gates
read their inputs from where the workflow puts them, and that the workflow is wired that way.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from gates import config, dep_guard, secret_scan, tests_gate, ticket_screen, traceability
from gates.config import load_config
from gates.report import CannotEvaluate, Result

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "gates.yml"
PREPARE = ROOT / ".github" / "actions" / "prepare"
GATE_JOBS = {"ticket_screen", "dep_guard", "osv", "secret_scan", "tests", "traceability"}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


# --- where the gates read their inputs ------------------------------------------------------


def test_defaults_are_a_valid_policy() -> None:
    cfg = load_config(ROOT / "defaults" / "gates.yaml")
    assert cfg.approved_packages == []
    assert config.kit_path(cfg.dep_guard.popular_names).exists()


def test_config_path_follows_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GATES_CONFIG", raising=False)
    assert config.config_path() == Path("gates.yaml")
    policy = tmp_path / "gates.yaml"
    policy.write_text((ROOT / "defaults" / "gates.yaml").read_text())
    monkeypatch.setenv("GATES_CONFIG", str(policy))
    assert config.config_path() == policy
    assert load_config().tickets.key_pattern == "[A-Z][A-Z0-9]+-[0-9]+"


def test_tickets_and_raw_dirs_follow_env(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config(ROOT / "gates.yaml")
    monkeypatch.delenv("GATES_TICKETS_DIR", raising=False)
    monkeypatch.delenv("GATES_RAW_DIR", raising=False)
    assert config.tickets_dir(cfg) == Path("tickets")
    assert config.raw_dir() == Path("reports")
    monkeypatch.setenv("GATES_TICKETS_DIR", "/policy/tickets")
    monkeypatch.setenv("GATES_RAW_DIR", "/raw")
    assert config.tickets_dir(cfg) == Path("/policy/tickets")
    assert config.raw_dir() == Path("/raw")
    assert traceability.ac_map_path() == Path("/raw/ac_map.json")


def test_kit_files_never_come_from_the_repo_under_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A PR plants an empty popular-names list where a cwd-relative lookup would find it.
    (tmp_path / "gates" / "data").mkdir(parents=True)
    (tmp_path / "gates" / "data" / "top_pypi.txt").write_text("")
    monkeypatch.chdir(tmp_path)
    resolved = config.kit_path("gates/data/top_pypi.txt")
    assert resolved == ROOT / "gates" / "data" / "top_pypi.txt"
    assert "requests" in dep_guard.load_popular(resolved)
    assert config.kit_path("/abs/list.txt") == Path("/abs/list.txt")


def test_ticket_screen_reads_tickets_from_env_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "PARK-104.json").write_text((ROOT / "tickets" / "PARK-104.json").read_text())
    monkeypatch.chdir(tmp_path)  # no tickets/ here
    monkeypatch.setenv("GATES_TICKETS_DIR", str(tmp_path))
    monkeypatch.setenv("GATES_PR_TITLE", "PARK-104: Show ride weather")
    out = ticket_screen.gate(load_config(ROOT / "gates.yaml"))
    assert out.result is Result.FAIL
    # Reported under the repo path, not the runner's folder.
    assert out.findings[0].file == "tickets/PARK-104.json"


def test_secret_scan_uses_config_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = tmp_path / "base-gitleaks.toml"
    policy.write_text("")
    monkeypatch.chdir(tmp_path)  # no .gitleaks.toml here
    monkeypatch.setenv("GATES_GITLEAKS_CONFIG", str(policy))
    seen: list[str] = []

    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        seen.append(cmd[cmd.index("--config") + 1])
        Path(cmd[cmd.index("--report-path") + 1]).write_text("[]")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(secret_scan.subprocess, "run", fake_run)
    assert secret_scan.run_gitleaks("main", "HEAD", "gitleaks") == []
    assert seen == [str(policy)]


# --- G5 split: run elsewhere, judge here ----------------------------------------------------

JUNIT_OK = """<?xml version="1.0"?>
<testsuites><testsuite tests="2" failures="0" errors="0" skipped="0">
<testcase classname="tests.test_a" name="test_1"/>
<testcase classname="tests.test_a" name="test_2"/>
</testsuite></testsuites>"""


def _raw(d: Path, exit_code: str = "0", pct: float = 90.0) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "junit.xml").write_text(JUNIT_OK)
    (d / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": pct}}))
    (d / "pytest_exit").write_text(exit_code + "\n")


def test_tests_gate_args_prints_coverage_sources(capsys: pytest.CaptureFixture[str]) -> None:
    assert tests_gate.main(["args"]) == 0
    assert capsys.readouterr().out.strip() == "--cov=app"


def test_tests_gate_rejects_unknown_mode() -> None:
    assert tests_gate.main(["nope"]) == 2


def test_judge_raw_passes_on_good_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _raw(tmp_path / "raw")
    monkeypatch.setenv("GATES_RAW_DIR", str(tmp_path / "raw"))
    out = tests_gate.judge_raw(load_config(ROOT / "gates.yaml"))
    assert out.result is Result.PASS
    assert out.reason == "2 passed, coverage 90.0% (floor 80%)"


def test_judge_raw_never_runs_pytest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _raw(tmp_path / "raw")
    monkeypatch.setenv("GATES_RAW_DIR", str(tmp_path / "raw"))

    def boom(*_: Any, **__: Any) -> None:
        raise AssertionError("judge mode must not run anything")

    monkeypatch.setattr(tests_gate.subprocess, "run", boom)
    tests_gate.judge_raw(load_config(ROOT / "gates.yaml"))


@pytest.mark.parametrize(
    ("setup", "match"),
    [
        (lambda d: None, "raw test results not found"),
        (lambda d: _raw(d, exit_code="x"), "pytest_exit is unreadable"),
        (lambda d: _raw(d, exit_code="4"), "pytest exited 4"),
        (
            lambda d: (_raw(d), (d / "coverage.json").write_text("{}")),
            "coverage.json is unreadable",
        ),
        (lambda d: (_raw(d), (d / "junit.xml").unlink()), "without complete results"),
    ],
)
def test_judge_raw_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setup: Any, match: str
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    setup(raw)
    monkeypatch.setenv("GATES_RAW_DIR", str(raw))
    with pytest.raises(CannotEvaluate, match=match):
        tests_gate.judge_raw(load_config(ROOT / "gates.yaml"))


# --- load_policy.sh: policy comes from the base commit --------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, str]:
    """A runner workspace: gates-src (this repo) and target (a repo with base and PR commits)."""
    (tmp_path / "gates-src").symlink_to(ROOT)
    target = tmp_path / "target"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.email", "t@example.invalid")
    _git(target, "config", "user.name", "t")
    (target / "gates.yaml").write_text("# base policy\n")
    (target / "tickets").mkdir()
    (target / "tickets" / "ACME-1.json").write_text('{"base": true}\n')
    _git(target, "add", ".")
    _git(target, "commit", "-qm", "base")
    base = _git(target, "rev-parse", "HEAD")
    # The PR relaxes the policy, cleans up its ticket, and adds a .gitleaks.toml.
    (target / "gates.yaml").write_text("# relaxed by the PR\n")
    (target / "tickets" / "ACME-1.json").write_text('{"base": false}\n')
    (target / ".gitleaks.toml").write_text("# PR's allowlist\n")
    _git(target, "add", ".")
    _git(target, "commit", "-qm", "pr")
    return tmp_path, base


def _load_policy(ws: Path, base: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GITHUB_WORKSPACE": str(ws), "GATES_BASE_REF": base}
    return subprocess.run(
        ["bash", str(PREPARE / "load_policy.sh")], env=env, capture_output=True, text=True
    )


def test_load_policy_reads_base_commit_not_pr(workspace: tuple[Path, str]) -> None:
    ws, base = workspace
    res = _load_policy(ws, base)
    assert res.returncode == 0, res.stderr
    assert (ws / "policy" / "gates.yaml").read_text() == "# base policy\n"
    assert (ws / "policy" / "tickets" / "ACME-1.json").read_text() == '{"base": true}\n'
    # .gitleaks.toml isn't on the base branch, so the kit default applies, not the PR's.
    default = (ROOT / "defaults" / "gitleaks.toml").read_text()
    assert (ws / "policy" / "gitleaks.toml").read_text() == default
    assert ".gitleaks.toml is not on the base branch" in res.stdout


def test_load_policy_uses_defaults_on_first_adoption(workspace: tuple[Path, str]) -> None:
    ws, _ = workspace
    target = ws / "target"
    _git(target, "checkout", "-q", "--orphan", "empty")
    _git(target, "rm", "-rqf", ".")
    _git(target, "commit", "-q", "--allow-empty", "-m", "empty base")
    res = _load_policy(ws, _git(target, "rev-parse", "HEAD"))
    assert res.returncode == 0, res.stderr
    default = (ROOT / "defaults" / "gates.yaml").read_text()
    assert (ws / "policy" / "gates.yaml").read_text() == default
    assert list((ws / "policy" / "tickets").iterdir()) == []


def test_load_policy_fails_closed_without_base_commit(workspace: tuple[Path, str]) -> None:
    ws, _ = workspace
    assert _load_policy(ws, "0" * 40).returncode != 0
    assert not (ws / "policy" / "gates.yaml").exists()


# --- the workflow's wiring ------------------------------------------------------------------


def _workflow() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    return data


def test_workflow_is_reusable() -> None:
    wf = _workflow()
    assert "workflow_call" in wf[True]  # PyYAML reads the bare key `on` as True
    assert wf["permissions"] == {"contents": "read"}


def test_every_job_runs_trusted_code_and_base_policy() -> None:
    for name, job in _workflow()["jobs"].items():
        first, second = job["steps"][0], job["steps"][1]
        assert first["with"]["repository"] == "${{ env.GATES_REPO }}", name
        assert first["with"]["ref"] == "${{ env.GATES_REF }}", name
        assert first["with"]["path"] == "gates-src", name
        assert second["uses"] == "./gates-src/.github/actions/prepare", name


def test_only_tests_run_executes_the_prs_code() -> None:
    jobs = _workflow()["jobs"]
    runs_pr_code = {
        name
        for name, job in jobs.items()
        for step in job["steps"]
        if "uv sync" in step.get("run", "") or "pytest" in step.get("run", "")
    }
    assert runs_pr_code == {"tests_run"}
    pytest_step = next(s for s in jobs["tests_run"]["steps"] if "pytest" in s.get("run", ""))
    assert "unset" in pytest_step["run"]  # gate settings don't leak into the PR's tests
    assert jobs["tests_run"]["needs"] == "dep_guard"
    assert jobs["tests_run"]["permissions"] == {"contents": "read"}
    assert any("tests_gate judge" in s.get("run", "") for s in jobs["tests"]["steps"])


def test_verdict_waits_for_every_gate() -> None:
    verdict = _workflow()["jobs"]["verdict"]
    assert verdict["name"] == "Gates verdict"
    assert verdict["if"] == "always()"
    assert set(verdict["needs"]) == GATE_JOBS


def test_gate_python_ignores_a_planted_gates_package(tmp_path: Path) -> None:
    # Gate steps run inside the repo under review. A PR that adds its own gates/ must not
    # replace the trusted gate code on PYTHONPATH.
    (tmp_path / "gates").mkdir()
    (tmp_path / "gates" / "__init__.py").write_text("")
    (tmp_path / "gates" / "tests_gate.py").write_text("print('HIJACKED')")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "GATES_CONFIG": str(ROOT / "gates.yaml")}

    def run(*flags: str) -> str:
        cmd = [sys.executable, *flags, "-m", "gates.tests_gate", "args"]
        return subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True).stdout

    assert run() == "HIJACKED\n"  # why the flag matters
    assert run("-P") == "--cov=app\n"
    assert _workflow()["env"]["GATE_PY"].endswith(" python -P")


def test_uv_version_matches_prepare_action() -> None:
    prepare = yaml.safe_load((PREPARE / "action.yml").read_text())
    uv = next(s for s in prepare["runs"]["steps"] if "setup-uv" in s.get("uses", ""))
    assert uv["with"]["version"] == _workflow()["env"]["UV_VERSION"]
