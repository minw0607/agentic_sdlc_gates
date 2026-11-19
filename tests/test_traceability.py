import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from gates import traceability
from gates.config import GatesConfig, load_config
from gates.report import CannotEvaluate, Result
from gates.traceability import Commit, judge, pr_commits, ticket_key

ROOT = Path(__file__).resolve().parent.parent
TICKETS = ROOT / "tickets"
CFG: GatesConfig = load_config(ROOT / "gates.yaml")


def _ac_map(**outcomes: str) -> dict[str, Any]:
    """_ac_map(AC_1="passed") -> criteria map for PARK-101."""
    crit: dict[str, list[dict[str, str]]] = {}
    for name, outcome in outcomes.items():
        cid = f"PARK-101/{name.replace('_', '-')}"
        crit.setdefault(cid, []).append({"nodeid": f"tests/t.py::{name}", "outcome": outcome})
    return {"criteria": crit, "tests": []}


ALL_PASS = _ac_map(AC_1="passed", AC_2="passed", AC_3="passed")
GOOD_COMMIT = Commit(sha="a" * 40, subject="Add filter", tickets=["PARK-101"], agent_session="s1")


def test_ticket_key_from_title() -> None:
    assert ticket_key("PARK-101: Filter rides", CFG.tickets.key_pattern) == "PARK-101"
    assert ticket_key("[PARK-7] fix", CFG.tickets.key_pattern) == "PARK-7"
    assert ticket_key("Tidy README", CFG.tickets.key_pattern) is None


def test_full_trace_passes() -> None:
    out = judge("PARK-101: Filter rides", [], CFG, TICKETS, ALL_PASS, [GOOD_COMMIT])
    assert out.result is Result.PASS
    assert out.reason == "PARK-101: 3/3 criteria covered, 1 commit(s) traced"
    assert out.details["ticket"]["summary"] == "Filter rides by maximum wait"
    assert out.details["commits"][0]["agent_session"] == "s1"
    assert all(r["covered"] for r in out.details["criteria"])


def test_missing_ticket_key_fails() -> None:
    out = judge("Filter rides", [], CFG, TICKETS, ALL_PASS, [GOOD_COMMIT])
    assert out.result is Result.FAIL
    assert "no ticket key" in out.reason


def test_no_ticket_label_warns() -> None:
    out = judge("Tidy README", ["docs", "no-ticket"], CFG, TICKETS, None, [])
    assert out.result is Result.WARN
    assert "no-ticket" in out.reason


def test_unknown_ticket_fails() -> None:
    out = judge("PARK-999: x", [], CFG, TICKETS, ALL_PASS, [GOOD_COMMIT])
    assert out.result is Result.FAIL
    assert out.reason == "Ticket PARK-999 not found in " + str(TICKETS) + "/"


def test_uncovered_criterion_fails() -> None:
    ac = _ac_map(AC_1="passed", AC_2="failed")
    out = judge("PARK-101: x", [], CFG, TICKETS, ac, [GOOD_COMMIT])
    assert out.result is Result.FAIL
    msgs = [f.message for f in out.findings]
    assert "PARK-101/AC-2 has no passing test" in msgs
    assert "PARK-101/AC-3 has no test" in msgs
    assert out.reason == "PARK-101: 1/3 criteria covered; 2 gap(s)"


def test_commit_without_trailer_fails() -> None:
    bad = Commit(sha="b" * 40, subject="wip", tickets=[])
    other = Commit(sha="c" * 40, subject="x", tickets=["PARK-102"])
    out = judge("PARK-101: x", [], CFG, TICKETS, ALL_PASS, [GOOD_COMMIT, bad, other])
    msgs = [f.message for f in out.findings]
    assert out.result is Result.FAIL
    assert "Commit bbbbbbb lacks `Ticket: PARK-101`" in msgs
    assert "Commit ccccccc lacks `Ticket: PARK-101` (has PARK-102)" in msgs


def test_no_commits_fails() -> None:
    out = judge("PARK-101: x", [], CFG, TICKETS, ALL_PASS, [])
    assert out.result is Result.FAIL


def test_missing_ac_map_cannot_evaluate() -> None:
    with pytest.raises(CannotEvaluate, match="ac_map"):
        judge("PARK-101: x", [], CFG, TICKETS, None, [GOOD_COMMIT])


# --- against a real git history ------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f").write_text("0")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feature")
    (tmp_path / "f").write_text("1")
    _git(tmp_path, "commit", "-qam", "Add filter\n\nTicket: PARK-101\nAgent-Session: abc-123")
    (tmp_path / "f").write_text("2")
    _git(tmp_path, "commit", "-qam", "Fix lint")
    return tmp_path


def test_pr_commits_reads_trailers(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    commits = pr_commits("main", "feature", "Ticket", "Agent-Session")
    assert [c.subject for c in commits] == ["Fix lint", "Add filter"]
    assert commits[0].tickets == []
    assert commits[1].tickets == ["PARK-101"]
    assert commits[1].agent_session == "abc-123"


def test_pr_commits_skips_merges(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    _git(repo, "checkout", "-q", "main")
    (repo / "g").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "main moves on")
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "merge", "-q", "--no-edit", "main")
    subjects = [c.subject for c in pr_commits("main", "feature", "Ticket", "Agent-Session")]
    assert subjects == ["Fix lint", "Add filter"]


def test_pr_commits_bad_ref_cannot_evaluate(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    with pytest.raises(CannotEvaluate):
        pr_commits("nope", "feature", "Ticket", "Agent-Session")


def test_gate_end_to_end(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "tickets").mkdir()
    (repo / "tickets" / "PARK-101.json").write_text((TICKETS / "PARK-101.json").read_text())
    (repo / "reports").mkdir()
    (repo / "reports" / "ac_map.json").write_text(json.dumps(ALL_PASS))
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GATES_PR_TITLE", "PARK-101: Filter rides")
    monkeypatch.setenv("GATES_PR_LABELS", "")
    monkeypatch.setenv("GATES_BASE_REF", "main")
    monkeypatch.setenv("GATES_HEAD_REF", "feature")
    out = traceability.gate(CFG)
    assert out.result is Result.FAIL  # "Fix lint" has no trailer
    assert [f.message for f in out.findings] == [
        f"Commit {_git(repo, 'rev-parse', '--short=7', 'feature')} lacks `Ticket: PARK-101`"
    ]
