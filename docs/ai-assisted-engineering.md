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
