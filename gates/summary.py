"""Check summary and final verdict: one table per PR, one trace, one evidence file.

Reads reports/<gate>.json from every gate job and:
- writes the summary to the job summary ($GITHUB_STEP_SUMMARY);
- creates or updates a single PR comment (found by a hidden marker);
- writes reports/evidence.json;
- exits 1 if any gate blocks.

This is the only check branch protection needs to require. GitHub counts a skipped job as
passing, so the verdict comes from the reports, not from job colors: a gate whose report
is missing counts as not_evaluated and blocks (unless the gate is off in gates.yaml).

Environment (all optional outside CI): GITHUB_TOKEN, GITHUB_REPOSITORY, GATES_PR_NUMBER,
GATES_HEAD_SHA, GITHUB_SERVER_URL, GITHUB_RUN_ID, GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gates.config import GatesConfig, Mode, load_config
from gates.report import REPORTS_DIR, GateReport, Result

MARKER = "<!-- agentic-sdlc-gates:summary -->"
GATES = [
    ("ticket_screen", "G1", "Ticket screen"),
    ("dep_guard", "G2", "Dependency guard"),
    ("osv", "G3", "Known vulnerabilities"),
    ("secret_scan", "G4", "Secret scan"),
    ("tests", "G5", "Tests and coverage"),
    ("traceability", "G6", "Traceability"),
]
ICON = {
    Result.PASS: "✅ pass",
    Result.FAIL: "❌ fail",
    Result.WARN: "⚠️ warn",
    Result.NOT_EVALUATED: "⏸️ not evaluated",
}


def load_reports(cfg: GatesConfig, reports_dir: Path) -> list[GateReport]:
    out = []
    for gate, gate_id, title in GATES:
        path = reports_dir / f"{gate}.json"
        mode = cfg.gates[gate].mode
        report: GateReport | None = None
        if path.exists():
            try:
                report = GateReport.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                reason = "Report is unreadable"
        else:
            reason = (
                "Turned off in gates.yaml"
                if mode is Mode.OFF
                else "Did not run (skipped or crashed before writing a report)"
            )
        if report is None:
            report = GateReport(
                gate=gate,
                gate_id=gate_id,
                title=title,
                mode=mode,
                blocking=mode is not Mode.OFF,
                result=Result.NOT_EVALUATED,
                reason=reason,
            )
        out.append(report)
    return out


def _cell(text: str) -> str:
    """Make PR-controlled text safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("<", "&lt;").replace("\n", " ").strip()


def render(reports: list[GateReport], run_url: str | None, head_sha: str | None) -> str:
    blockers = [r for r in reports if r.blocking]
    if blockers:
        verdict = "❌ **Blocked** by " + ", ".join(f"{r.gate_id} {r.title}" for r in blockers)
    else:
        verdict = "✅ **All required gates passed**"
    details_link = f"[details]({run_url})" if run_url else "details below"
    lines = [
        MARKER,
        "## Release gates",
        "",
        verdict,
        "",
        "| Gate | Result | Why |",
        "|---|---|---|",
    ]
    for r in reports:
        lines.append(f"| {r.gate_id} {r.title} | {ICON[r.result]} | {_cell(r.reason)} |")
    lines += ["", f"Run: {details_link}" + (f" · commit `{head_sha[:7]}`" if head_sha else "")]

    with_findings = [r for r in reports if r.findings]
    if with_findings:
        lines += ["", "### Findings", ""]
        for r in with_findings:
            lines.append(f"**{r.gate_id} {r.title}**")
            lines.append("")
            for f in r.findings:
                where = f" (`{f.file}:{f.line}`)" if f.file and f.line else ""
                where = where or (f" (`{f.file}`)" if f.file else "")
                lines.append(f"- {ICON[f.result].split()[0]} {_cell(f.message)}{where}")
            lines.append("")

    trace = next((r for r in reports if r.gate == "traceability"), None)
    if trace and trace.details.get("ticket"):
        lines += render_trace(trace.details)
    return "\n".join(lines).rstrip() + "\n"


def render_trace(d: dict[str, Any]) -> list[str]:
    t = d["ticket"]
    title = f"{t['key']}: {_cell(t.get('summary', ''))}".rstrip(": ")
    risk = f" · risk **{t['risk']}**" if t.get("risk") else ""
    lines = ["", "### Trace", "", f"**{title}**{risk}", ""]
    if d.get("criteria"):
        lines += ["| Criterion | Tests | Covered |", "|---|---|---|"]
        for c in d["criteria"]:
            tests = (
                "<br>".join(
                    f"`{_cell(x['nodeid'].split('::')[-1])}` {x['outcome']}" for x in c["tests"]
                )
                or "none"
            )
            covered = "✅" if c["covered"] else "❌"
            lines.append(
                f"| **{c['id'].split('/')[-1]}** {_cell(c['text'])} | {tests} | {covered} |"
            )
    if d.get("commits"):
        lines += ["", "| Commit | Ticket | Agent session |", "|---|---|---|"]
        for c in d["commits"]:
            tickets = ", ".join(c["tickets"]) or "—"
            session = f"`{_cell(c['agent_session'])}`" if c.get("agent_session") else "—"
            lines.append(f"| `{c['sha'][:7]}` {_cell(c['subject'])} | {tickets} | {session} |")
    return lines


def evidence(
    reports: list[GateReport], run_url: str | None, head_sha: str | None
) -> dict[str, Any]:
    trace = next((r.details for r in reports if r.gate == "traceability"), {})
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "pull_request": os.environ.get("GATES_PR_NUMBER"),
        "head_sha": head_sha,
        "run_url": run_url,
        "verdict": "blocked" if any(r.blocking for r in reports) else "passed",
        "gates": [r.model_dump(mode="json") for r in reports],
        "trace": trace,
    }


def _api(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentic-sdlc-gates",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


BOT_LOGIN = "github-actions[bot]"  # the author of comments made with the workflow's token
PAGE = 100


def _is_ours(comment: dict[str, Any]) -> bool:
    """Our summary: carries the marker and was posted by the workflow, not pasted by a person."""
    user = comment.get("user") or {}
    return MARKER in (comment.get("body") or "") and user.get("login") == BOT_LOGIN


def upsert_comment(repo: str, pr: str, token: str, body: str, api: str) -> str:
    """Update the summary comment on the PR, or create it. Returns 'updated' or 'created'."""
    page = 1
    while True:
        url = f"{api}/repos/{repo}/issues/{pr}/comments?per_page={PAGE}&page={page}"
        comments = _api("GET", url, token)
        mine = next((c for c in comments if _is_ours(c)), None)
        if mine:
            _api("PATCH", f"{api}/repos/{repo}/issues/comments/{mine['id']}", token, {"body": body})
            return "updated"
        if len(comments) < PAGE:
            break
        page += 1
    _api("POST", f"{api}/repos/{repo}/issues/{pr}/comments", token, {"body": body})
    return "created"


def main() -> int:
    cfg = load_config()
    reports = load_reports(cfg, REPORTS_DIR)
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else None
    head_sha = os.environ.get("GATES_HEAD_SHA")

    body = render(reports, run_url, head_sha)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "summary.md").write_text(body, encoding="utf-8")
    (REPORTS_DIR / "evidence.json").write_text(
        json.dumps(evidence(reports, run_url, head_sha), indent=2) + "\n", encoding="utf-8"
    )
    if step := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step, "a", encoding="utf-8") as f:
            f.write(body)
    print(body)

    token, pr = os.environ.get("GITHUB_TOKEN"), os.environ.get("GATES_PR_NUMBER")
    if token and repo and pr:
        api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        try:
            print(f"PR comment {upsert_comment(repo, pr, token, body, api)}")
        except (urllib.error.URLError, TimeoutError) as e:
            # Reporting only: the verdict below still decides the check.
            print(f"::warning::Could not post the PR comment: {e}")

    blocked = [r.gate_id for r in reports if r.blocking]
    if blocked:
        print(f"::error::Blocked by {', '.join(blocked)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
