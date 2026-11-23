# AI-assisted engineering log

What was delegated to Claude Code, what changed after review, and what was learned. One entry per block of the [development plan](dev-plan.md).

## Day 1 morning (Nov 19): foundation

**Delegated.** `CLAUDE.md`; project setup (uv, Python 3.11, ruff, strict mypy, pytest-cov); the sample FastAPI service (`rides`, `dining`, `payments` stub) with synthetic data; baseline tests; `gates.yaml` with a validating loader (`gates/config.py`); a ticket model and loader (`gates/tickets.py`); the acceptance-criteria pytest plugin (`gates/pytest_ac.py`); tickets PARK-101 to PARK-105.

**Found during the work.**
- **The baseline must leave each scenario's work undone.** Plan section 5 lists `GET /rides?max_wait=30` and party-size limits as part of the service, but those are exactly what S1 (PARK-101) and S4 (PARK-104) ask the agent to build. The baseline has neither. Likewise the deposit calculator keeps a real float-rounding bug (5 guests × $15 with 2.5% off gives $73.12, not $73.13) so that PARK-105 fixes something real.
- **A dependency warning was itself a dependency-guard test.** Starlette 1.10 warned that its test client now wants `httpx2` instead of `httpx`. Before adding it, the name was checked: Starlette's own source imports it, it is published from the pydantic GitHub organization, and its first release was May 2026. It replaced `httpx`. An agent following the warning blindly would have been doing what G2 exists to check.
- **Plugin state had to be per session.** The first version of the criteria plugin kept results in module globals. The plugin's own tests run a nested pytest in the same process, which would have wiped the outer session's results. State now lives on a recorder object registered per session.
- **Scenario names were checked on PyPI (read only, nothing installed).** `queueline-sdk`, the SDK named in PARK-103, returns 404.

**Verified.**
- `uv run pytest --cov=app --cov=gates`: 32 passed, coverage 99% (floor in `gates.yaml` is 80%).
- `reports/ac_map.json` is written on every run. No test is marked with a criterion yet; the scenarios add the first ones.
- `ruff check`, `ruff format --check` and `mypy --strict` are clean.

## Day 1 afternoon (Nov 19): gates G2–G6 and the verdict

**Delegated.** A shared report format and fail-closed runner (`gates/report.py`); the dependency guard (G2); wrappers for OSV-Scanner (G3), gitleaks (G4) and pytest with coverage (G5); traceability (G6); the PR summary, evidence file and verdict (`gates/summary.py`); `.gitleaks.toml`; the `factory-gates` workflow.

**Changed from the plan, after review.**
- **One required check, the verdict.** GitHub counts a skipped job as passing. If G2 fails, G5 and G6 are skipped, and if those were required checks they would read as green. The verdict job reads every gate's report instead, and a missing report blocks.
- **No-ticket PRs warn instead of failing.** Under the plan's rule, every chore PR (including the plan's own Day 1 no-op PR) would fail traceability. A `no-ticket` label now makes G6 warn, and the summary shows it.
- **The lookalike check skips names under 5 characters.** Within 2 edits, short real names sit next to each other (`rich`, `rope`, `six`). None of the 10 approved packages or 8 other common libraries tried trip the check; `reqeusts` does.
- **Approved packages skip the lookalike check.** `httpx2`, which this repo uses, is one edit from `httpx`. Approval is the human override.
- **Tickets are excluded from the secret scan.** The PARK-102 ticket quotes the fake key on purpose. The scan is about what the agent commits.
- **G3 runs alongside G2 rather than after it.** It only reads `uv.lock` and installs nothing, so waiting gains nothing and hides findings when G2 fails.
- **Coverage is measured over `app/` only.** Including the gate code inflated the number the S1 demo shows; the gates have their own tests.
- **G1 is set to `off` until Day 2,** so it reports "not evaluated (turned off)" rather than a missing report that blocks every PR.

**Found during the work.**
- **YAML reads a bare `off` as `false`.** Setting G1 to `mode: off` broke config loading. `gates.yaml` now quotes it, and the loader also accepts a bare `off`, since a team customizing the file would hit the same trap.
- **Tool versions follow our own policy.** The latest OSV-Scanner (v2.7.1) was 10 days old, under the 30-day rule G2 applies to packages, so the workflow pins v2.7.0. Both scanner binaries are checksum-verified, and every action is pinned by commit SHA.
- **OSV-Scanner reads `uv.lock` directly** (33 packages found), so no export step is needed.
- **A first local secret-scan test passed when it should have failed.** That was a test setup error (both commits were on `main`, so the scanned range was empty), not a gate bug. Re-run with the right base, it caught the key, ignored the ticket copy, and kept the key out of the report.
- **The PR title is untrusted input.** The workflow passes it through an environment variable, never inlined into a shell script, and the summary escapes PR-controlled text in table cells.
- **The S3 lookalike `reqeusts` does not exist on PyPI** (404, checked read-only).

**Verified.**
- 116 tests pass locally; ruff and strict mypy are clean.
- Live runs: gitleaks caught the demo key in app code and ignored it in `tickets/`; OSV-Scanner on `uv.lock` passed; the tests gate passed at 100% coverage of `app/`.
- CI on [PR #1](https://github.com/minw0607/agentic_sdlc_gates/pull/1): every job passed on the first run, and the summary comment showed G1 as turned off, G2–G5 passing, and G6 warning for `no-ticket`.

## Day 1 afternoon: S1–S3 scenario pull requests (2026-11-19)

**Delegated:** producing the three scenario branches and PRs, and the honesty record in
`scripts/seed_scenarios.md`.

**Changes from the plan:** the plan has the agent start from `scripts/start_ticket.sh`, which is
Day 2 work, so these branches were made directly from the tickets without the ticket screen.
Recorded as such.

**Findings:** GitHub push protection did not block the made-up `PARKWX-` key, so CI is the one
blocking S2, as the plan wanted. In S3 the summary lists G5 and G6 as blockers alongside G2,
because a gate that didn't run fails closed; accurate, but the demo should say they were skipped
because of G2. The first version of this record quoted the fake key and G4 blocked its own
PR (#5) at `scripts/seed_scenarios.md:31`; the gate was right, so the record now refers to the key
without repeating it, on a fresh branch (#5 closed).

**Verified:** CI on PR #2 all green with 3/3 criteria traced; PR #3 blocked by G4 at
`app/rides/weather.py:8` with every other gate passing; PR #4 blocked by G2 with both expected
messages and G5 skipped. Both S3 names were 404 on PyPI before the push, and nothing was installed.

## Day 2 morning: ticket screen, agent controls and S4 (2026-11-19)

**Delegated:** `gates/ticket_screen.py` (G1) and its tests, `.claude/settings.json`,
`.claude/hooks/guard.py` and `audit.py` and their tests, `scripts/start_ticket.sh`, the dummy
`.env`, and the S4 branch and PR.

**Changes from the plan:**
- G1 runs in parallel with the other gates, not first. Nothing in CI reads the ticket as
  instructions, so ordering buys nothing, and S4 can show the code passing every other gate.
- The audit log can't see blocked calls (they never reach PostToolUse), so the guard writes its
  own `denied` entries. Entries store a SHA-256 of the input, never the input, so a secret the
  agent tried to read or send can't land in the log.
- The hooks are stdlib only and run on the system `python3` (3.9 here), not the project's 3.11
  environment, so ruff's `datetime.UTC` rewrite was reverted with a `noqa`.
- Locally the screen prints the matched lines; in CI it reports only field, line and pattern, so
  the PR comment doesn't carry the injection onward.

**Findings:**
- The first dummy `.env` values were realistic enough to trip gitleaks' generic-key rule. The
  values are now plainly `dummy` rather than allowlisting `.env`, so a real `.env` committed later
  is still caught.
- Headless `claude -p` on the build machine wasn't logged in, so the live check that the guard's
  deny is honored by Claude Code 2.1.205 is still open; the hook's JSON output is unit-tested.
- The screen's first local output printed one injected line five times (once per pattern);
  it now groups patterns per line, which reads better on screen.

**Verified:** 196 tests pass, including 10 planted patterns, 5 clean tickets, 24 blocked and 11
allowed tool calls, and fail-closed cases. PR #7 green on every gate including G1. PR #8 (S4)
blocked by G1 only, with G2–G6 passing and the injected text absent from the PR comment.

## Reusable workflow (2026-11-23)

**Delegated:** a review of the repo, then `.github/workflows/gates.yml` (reusable), its shared
setup in `.github/actions/prepare/`, `defaults/`, the environment-variable options in the gates,
the split of `tests_gate` into run, `args` and `judge`, `tests/test_reusable_workflow.py`, and
[docs/reusable-workflow.md](reusable-workflow.md).

**Changes from the plan:**
- The review found that `factory-gates.yml` runs gate code and policy from the PR being judged,
  so a PR could edit the gates or `.gitleaks.toml`. The reusable workflow takes code from this
  repo at a pinned version and policy from the base commit. In this repo, `gates/**`,
  `defaults/**`, `.gitleaks.toml` and `tickets/**` joined the high-risk paths.
- G5 is split in two. One job runs the PR's tests and writes raw results; a separate job that
  runs none of the PR's code judges them.
- This repo's own PRs stay on `factory-gates.yml` for now: switching renames the required check,
  and the first PR would be judged by gate code on `main` that doesn't yet know the new options.

**Findings:**
- A local job-by-job simulation caught two bugs that the unit tests had missed. First, gate
  steps run inside the repo under review, and `python -m gates.x` imported that repo's `gates/`
  folder ahead of the trusted copy, so a PR could replace the gates by adding one. Gate steps now
  run Python with `-P`. Second, the workflow's `GATES_*` variables leaked into the PR's own test
  run and changed its results, so that step now clears them.
- `scripts/start_ticket.sh` used `uuidgen`, which isn't on every Linux machine. It now uses
  Python's `uuid`.

**Verified:** 220 tests pass, ruff and mypy clean. A local simulation ran the jobs in order
(policy from base, G1, G2, the tests run and judge, G6, the verdict) against a copy of this repo
with a base commit and a PR commit. G3 and G4 weren't simulated (no scanner binaries locally). Not
yet run on GitHub.
