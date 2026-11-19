"""G6 traceability: ticket -> acceptance criteria -> passing tests -> commits.

Fails when:
- the PR title has no ticket key (unless the PR carries the no-ticket label, which warns);
- the ticket file is missing;
- an acceptance criterion has no passing test (tests declare coverage with
  ``@pytest.mark.ac("PARK-101/AC-1")``; results come from reports/ac_map.json);
- a commit in the PR lacks a ``Ticket:`` trailer naming the PR's ticket.

The trace it builds (criteria, tests, commits, agent session ids) feeds the PR summary.

Environment: GATES_PR_TITLE, GATES_PR_LABELS (comma separated), GATES_BASE_REF,
GATES_HEAD_REF (the PR's head commit; merge commits are skipped).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gates.config import GatesConfig
from gates.report import CannotEvaluate, Finding, Outcome, Result, env, run_gate
from gates.tickets import Ticket, load_ticket

AC_MAP = Path("reports/ac_map.json")
FIELD, RECORD = "\x1f", "\x1e"


class Commit(BaseModel):
    sha: str
    subject: str
    tickets: list[str]
    agent_session: str | None = None


def ticket_key(title: str, pattern: str) -> str | None:
    m = re.search(pattern, title)
    return m.group(0) if m else None


def pr_commits(base: str, head: str, ticket_trailer: str, session_trailer: str) -> list[Commit]:
    fmt = FIELD.join(
        [
            "%H",
            "%s",
            f"%(trailers:key={ticket_trailer},valueonly,separator=%x2C)",
            f"%(trailers:key={session_trailer},valueonly,separator=%x2C)",
        ]
    )
    res = subprocess.run(
        ["git", "log", "--no-merges", f"--format={fmt}{RECORD}", f"{base}..{head}"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise CannotEvaluate(f"git log failed: {res.stderr.strip()}")
    commits = []
    for record in res.stdout.split(RECORD):
        record = record.strip("\n")
        if not record:
            continue
        sha, subject, tickets, session = record.split(FIELD)
        commits.append(
            Commit(
                sha=sha,
                subject=subject,
                tickets=[t.strip() for t in tickets.split(",") if t.strip()],
                agent_session=session.split(",")[0].strip() or None,
            )
        )
    return commits


def trace_criteria(ticket: Ticket, ac_map: dict[str, Any]) -> list[dict[str, Any]]:
    by_criterion: dict[str, list[dict[str, str]]] = ac_map.get("criteria", {})
    rows = []
    for c in ticket.acceptance_criteria:
        cid = f"{ticket.key}/{c.id}"
        tests = by_criterion.get(cid, [])
        rows.append(
            {
                "id": cid,
                "text": c.text,
                "tests": tests,
                "covered": any(t["outcome"] == "passed" for t in tests),
            }
        )
    return rows


def judge(
    title: str,
    labels: list[str],
    cfg: GatesConfig,
    tickets_dir: Path,
    ac_map: dict[str, Any] | None,
    commits: list[Commit],
) -> Outcome:
    t = cfg.tickets
    key = ticket_key(title, t.key_pattern)
    commit_rows = [c.model_dump() for c in commits]
    if key is None:
        if t.no_ticket_label in labels:
            return Outcome(
                result=Result.WARN,
                reason=f"No ticket: PR is labelled `{t.no_ticket_label}`",
                details={"ticket": None, "commits": commit_rows},
            )
        return Outcome(
            result=Result.FAIL,
            reason=f"PR title has no ticket key (expected {t.key_pattern})",
            findings=[
                Finding(
                    result=Result.FAIL,
                    message=f"Add the ticket key to the title, or the `{t.no_ticket_label}` label",
                )
            ],
            details={"ticket": None, "commits": commit_rows},
        )

    try:
        ticket = load_ticket(key, tickets_dir)
    except FileNotFoundError:
        return Outcome(
            result=Result.FAIL,
            reason=f"Ticket {key} not found in {tickets_dir}/",
            findings=[Finding(result=Result.FAIL, message=f"No file {tickets_dir}/{key}.json")],
            details={"ticket": {"key": key}, "commits": commit_rows},
        )
    if ac_map is None:
        raise CannotEvaluate(f"{AC_MAP} not found; the tests gate did not produce it")

    criteria = trace_criteria(ticket, ac_map)
    findings: list[Finding] = []
    for row in criteria:
        if not row["covered"]:
            why = "has no test" if not row["tests"] else "has no passing test"
            findings.append(Finding(result=Result.FAIL, message=f"{row['id']} {why}"))
    if not commits:
        findings.append(Finding(result=Result.FAIL, message="PR has no commits to trace"))
    for c in commits:
        if key not in c.tickets:
            have = f" (has {', '.join(c.tickets)})" if c.tickets else ""
            findings.append(
                Finding(
                    result=Result.FAIL,
                    message=f"Commit {c.sha[:7]} lacks `{t.commit_trailer}: {key}`{have}",
                )
            )

    covered = sum(r["covered"] for r in criteria)
    details = {
        "ticket": {"key": ticket.key, "summary": ticket.summary, "risk": ticket.risk},
        "criteria": criteria,
        "commits": commit_rows,
    }
    if findings:
        return Outcome(
            result=Result.FAIL,
            reason=f"{key}: {covered}/{len(criteria)} criteria covered; {len(findings)} gap(s)",
            findings=findings,
            details=details,
        )
    return Outcome(
        result=Result.PASS,
        reason=(
            f"{key}: {covered}/{len(criteria)} criteria covered, {len(commits)} commit(s) traced"
        ),
        details=details,
    )


def gate(cfg: GatesConfig) -> Outcome:
    title = env("GATES_PR_TITLE")
    labels = [x.strip() for x in os.environ.get("GATES_PR_LABELS", "").split(",") if x.strip()]
    commits = pr_commits(
        env("GATES_BASE_REF"),
        os.environ.get("GATES_HEAD_REF", "HEAD"),
        cfg.tickets.commit_trailer,
        cfg.tickets.agent_session_trailer,
    )
    ac_map = json.loads(AC_MAP.read_text()) if AC_MAP.exists() else None
    return judge(title, labels, cfg, Path(cfg.tickets.dir), ac_map, commits)


def main() -> int:
    return run_gate("traceability", "G6", "Traceability", gate)


if __name__ == "__main__":
    sys.exit(main())
