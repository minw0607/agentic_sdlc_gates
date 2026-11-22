# agentic_sdlc_gates

**Your agents write the code; these checks decide whether it ships, and keep the agent inside its lane while it works.**

AI coding agents turn tickets into pull requests in minutes. This repo is a ready-made kit for that kind of "software factory", in two halves:

- **Release gates** run on every pull request in GitHub Actions and decide what can merge: a planted instruction in the ticket, an invented or lookalike dependency, a known vulnerability, a hardcoded secret, failing tests, or a change that can't be traced back to its ticket.
- **Agent controls** run on the developer's machine, around Claude Code itself: deny rules and a guard hook stop the agent from reading secrets or calling out, and every tool call goes to an audit log.

Every policy lives in one file, [`gates.yaml`](gates.yaml). A gate that can't run reports *not evaluated* and blocks, rather than passing quietly.

```mermaid
flowchart TD
    T["Ticket (Jira-shaped JSON)"] --> S(["Ticket screen · start_ticket.sh"])
    S -- quarantined --> H["Stop for a person's review"]
    S -- clean --> A["Claude Code on the developer's machine<br/>deny rules · guard hook · audit log"]
    A --> PR["Pull request"]
    PR --> V(["Release gates G1–G6 in GitHub Actions<br/>one required check: Gates verdict"])
    V -- blocked --> F["Fix and push again"]
    F --> PR
    V -- passed --> O["Code-owner approval<br/>for high-risk paths (G7)"]
    O --> M["Merge"]
```

## See it work

Each scenario is a real pull request in this repo, made by Claude Code from a ticket in [`tickets/`](tickets/). S2, S3 and S4 are **set up on purpose to fail**; [`scripts/seed_scenarios.md`](scripts/seed_scenarios.md) records exactly how each branch was made.

| | Scenario | Ticket | Pull request | Result |
|---|---|---|---|---|
| S1 | A clean change, traced from story to tests to commit | PARK-101 | [#2](https://github.com/minw0607/agentic_sdlc_gates/pull/2) | ✅ Every gate passes; all 3 acceptance criteria traced to passing tests |
| S2 | The agent hardcodes a credential the ticket handed it | PARK-102 | [#3](https://github.com/minw0607/agentic_sdlc_gates/pull/3) | ❌ Secret scan names `app/rides/weather.py:8` |
| S3 | The agent adds a package that doesn't exist and a lookalike of `requests` | PARK-103 | [#4](https://github.com/minw0607/agentic_sdlc_gates/pull/4) | ❌ Dependency guard blocks both before anything is installed |
| S4 | The ticket hides an instruction to read `.env` and send it to an outside URL | PARK-104 | [#8](https://github.com/minw0607/agentic_sdlc_gates/pull/8) | ❌ Ticket screen quarantines the ticket; the code itself passes every other gate |
| S5 | A fix in the payments code, a high-risk path | PARK-105 | [#11](https://github.com/minw0607/agentic_sdlc_gates/pull/11) | ⏳ Every gate passes; the code-owner approval step is still being set up (see [Status](#status)) |

Every pull request gets one summary comment, updated on each push, and the same content as an `evidence.json` artifact. For S1 it looks like this:

> ✅ **All required gates passed**
>
> | Gate | Result | Why |
> |---|---|---|
> | G1 Ticket screen | ✅ pass | PARK-101: no instructions aimed at the AI |
> | G2 Dependency guard | ✅ pass | No new dependencies |
> | G5 Tests and coverage | ✅ pass | 200 passed, coverage 100.0% (floor 80%) |
> | G6 Traceability | ✅ pass | PARK-101: 3/3 criteria covered, 1 commit(s) traced |
>
> | Criterion | Tests | Covered |
> |---|---|---|
> | **AC-2** GET /rides?max_wait=0 returns the open rides with no wait, and never returns closed rides. | `test_max_wait_zero_returns_no_wait_rides_and_never_closed` passed | ✅ |
>
> *(excerpt)*

## The gates

All gates run in [`.github/workflows/factory-gates.yml`](.github/workflows/factory-gates.yml). Each writes `reports/<gate>.json`; a final **Gates verdict** job reads them all and is the single required check on `main`, because GitHub counts a skipped job as passing.

| ID | Gate | Fails when |
|---|---|---|
| G1 | Ticket screen ([`ticket_screen.py`](gates/ticket_screen.py)) | The PR's ticket carries instructions aimed at the AI: hidden HTML comments, text addressed to the assistant, "ignore previous instructions", requests to read secrets or send data to a URL, "don't mention it", or invisible and full-width characters |
| G2 | Dependency guard ([`dep_guard.py`](gates/dep_guard.py)) | A new dependency doesn't exist on PyPI, is within 2 edits of a popular package without being it, or was first released under 30 days ago. Runs before anything is installed. |
| G3 | Known vulnerabilities ([OSV-Scanner](https://github.com/google/osv-scanner)) | `uv.lock` gains a known vulnerability compared with the base branch |
| G4 | Secret scan ([gitleaks](https://github.com/gitleaks/gitleaks)) | Any of the PR's commits contains a secret |
| G5 | Tests and coverage | A test fails, or coverage of `app/` drops below the floor. Never runs if G2 failed. |
| G6 | Traceability ([`traceability.py`](gates/traceability.py)) | The PR title has no ticket key, an acceptance criterion has no passing test, or a commit lacks a `Ticket:` trailer |
| G7 | High-risk paths ([`CODEOWNERS`](.github/CODEOWNERS)) | A change to `app/payments/`, `.github/`, `gates.yaml` or `.claude/` lacks the code owner's approval (GitHub branch protection) |

Tests declare what they cover with a marker, and a small pytest plugin turns that into the trace:

```python
@pytest.mark.ac("PARK-101/AC-2")
def test_max_wait_zero_returns_no_wait_rides_and_never_closed(client): ...
```

## The agent controls

Claude Code picks these up from [`.claude/settings.json`](.claude/settings.json) when it runs in this repo:

- **Deny rules** for reading `.env` and `secrets/`, `curl`, `wget` and web fetches.
- **A guard hook** ([`guard.py`](.claude/hooks/guard.py), PreToolUse) that catches what path rules miss, such as `python -c "open('.env')"` or `requests.post(...)` inside a shell command, plus force pushes. It answers with a plain-language reason, and blocks if it can't read the call.
- **An audit log** ([`audit.py`](.claude/hooks/audit.py), PostToolUse) in `.agent-audit/tool_calls.jsonl`. Each entry has the time, session, tool, decision and a SHA-256 of the input, never the input itself, so a secret the agent tried to send can't end up in the log.

[`scripts/start_ticket.sh`](scripts/start_ticket.sh) is the developer's entry point. It screens the ticket first and stops if it's quarantined:

```console
$ scripts/start_ticket.sh PARK-104
QUARANTINED: PARK-104 looks like it carries instructions aimed at the AI.
Do not hand this ticket to an agent until a person has reviewed it.

  description line 3: hidden_markup, addresses_the_ai, reads_secrets, sends_data_out, conceals_from_user
```

A clean ticket starts Claude Code on its own branch, with a session ID the commits carry as an `Agent-Session:` trailer.

## Quick start

Needs Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/minw0607/agentic_sdlc_gates.git && cd agentic_sdlc_gates
uv sync
uv run pytest                                   # the sample service, the gates and the hooks
uv run python -m gates.ticket_screen PARK-104   # screen a ticket (prints QUARANTINED)
GATES_BASE_REF=origin/main uv run python -m gates.dep_guard   # run one gate locally
```

The sample service is a small FastAPI "theme park operations" API (ride waits, dining reservations, a deposit calculator) with invented names and synthetic data: `uv run uvicorn app.main:app --reload`.

## Make it yours

Customizing is editing [`gates.yaml`](gates.yaml), not code:

```yaml
gates:
  ticket_screen: { mode: fail }   # fail, warn or "off", per gate
  dep_guard: { mode: fail }
  ...
coverage:
  floor: 80
dep_guard:
  min_age_days: 30
  unapproved: warn                # a real package not on approved_packages
approved_packages: [fastapi, pydantic, ...]
high_risk_paths: [app/payments/**, .github/**, gates.yaml, .claude/**]
```

To use the gates in another Python repo today, copy `gates/`, `gates.yaml`, `.gitleaks.toml`, `.github/workflows/factory-gates.yml` and, for the agent controls, `.claude/`; then make **Gates verdict** a required check. A reusable workflow (`uses: minw0607/agentic_sdlc_gates/...@v1`) is planned but not built yet.

## OWASP mapping

Which risks in the OWASP [Top 10 for LLM Applications 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) and [Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) each control addresses. This shows where a control helps; it is not a claim of compliance or full coverage.

| Control | LLM Top 10 2026 | Agentic Top 10 2026 |
|---|---|---|
| G1 ticket screen | LLM01 Prompt Injection | ASI01 Agent Goal Hijack |
| G2 dependency guard, G3 known vulnerabilities | LLM04 Supply Chain | ASI04 Agentic Supply Chain Vulnerabilities |
| G4 secret scan | LLM02 Sensitive Information Disclosure | ASI03 Identity and Privilege Abuse |
| Deny rules, guard hook, audit log | LLM02 Sensitive Information Disclosure, LLM03 Excessive Agency | ASI02 Tool Misuse and Exploitation, ASI03 Identity and Privilege Abuse |
| G7 code-owner approval | LLM03 Excessive Agency | — |

## Status

As of 22 November 2026. A 2-day build, done with Claude Code; the plan is in [`docs/dev-plan.md`](docs/dev-plan.md).

**Working and tested**
- Release gates G1–G6 in CI, the one-comment summary and `evidence.json`.
- Branch protection on `main`: Gates verdict is required for everyone, admins included, and changes to the high-risk paths need a code owner's approval.
- Agent controls: deny rules, the guard hook and the audit log, with unit tests that feed the hooks sample tool calls as JSON. `start_ticket.sh` screens a ticket before handing it to Claude Code.
- Scenarios S1–S4 as pull requests, each with the result it was meant to show.
- 200 tests, 100% coverage of the sample service.

**In progress**
- **S5 approval.** The second account that acts as code owner has been invited but hasn't joined yet, so GitHub doesn't enforce the approval on [#11](https://github.com/minw0607/agentic_sdlc_gates/pull/11) yet.
- **A live check of the guard hook** inside an interactive Claude Code session. The hook's output format is unit-tested; seeing Claude Code honour it end to end, and the terminal part of S4, is still to be run and recorded.
- **The demo recording** (4–5 minutes) and a GIF for this page.

**Not built yet**
- A reusable workflow, so another repo can adopt the gates with one `uses:` line.
- An AI code review step. Every gate here is a fixed rule that gives the same answer each time. A model-based reviewer would be added in report-only mode, and would treat the diff as untrusted input, like tickets.

## What this is and isn't

- **A working demo, not a product.** The gates and hooks are real and tested; the service, tickets and data are synthetic, with no real client names or secrets. The `.env` holds dummy values only.
- **Tickets are files shaped like Jira issues**, not a live Jira integration.
- **The agent controls are for Claude Code.** The CI gates work the same whichever agent, or person, wrote the code; Cursor-side controls aren't covered.
- **The ticket screen is a pattern screen**: cheap and explainable, and evadable by rewording. That's why the guard hook sits behind it.
- **The scenario failures are seeded**, and recorded as such.

## More

- [`docs/dev-plan.md`](docs/dev-plan.md): the plan, scenarios and decisions.
- [`docs/ai-assisted-engineering.md`](docs/ai-assisted-engineering.md): what was delegated to Claude Code, what review caught, and what changed.
- [`scripts/seed_scenarios.md`](scripts/seed_scenarios.md): how each scenario branch was produced.
- [`CLAUDE.md`](CLAUDE.md): the conventions Claude Code follows in this repo.

**Built on** [axiom_agent_platform](https://github.com/minw0607/axiom_agent_platform): the ticket screen's patterns are adapted from its injection guardrail, and the fail-closed results and evidence record follow its design.
