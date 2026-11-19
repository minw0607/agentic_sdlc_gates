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
