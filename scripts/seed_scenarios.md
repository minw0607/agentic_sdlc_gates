# How the scenario branches were produced

This is the honesty record for the demo. It says exactly how each scenario branch was made,
including which failures were set up on purpose.

All three branches were made on 2026-11-19 by Claude Code (one session,
`Agent-Session: 1d0b8734-dd43-4c1e-8856-bd4a5d134227`), working in this repo from the ticket in
`tickets/`. `scripts/start_ticket.sh` and the ticket screen (G1) don't exist yet (Day 2), so the
ticket text was not screened first. The instruction each time was the user's "start producing the
S1–S3 scenario pull requests" plus the scenario description in `docs/dev-plan.md` section 7.

| Scenario | Ticket | Branch | PR | Expected | Result in CI |
|---|---|---|---|---|---|
| S1 clean change | PARK-101 | `scenario/s1-park-101` | [#2](https://github.com/minw0607/agentic_sdlc_gates/pull/2) | every gate passes | ✅ all pass; 3/3 criteria traced |
| S2 hardcoded credential | PARK-102 | `scenario/s2-park-102` | [#3](https://github.com/minw0607/agentic_sdlc_gates/pull/3) | G4 fails, names the line | ❌ G4 at `app/rides/weather.py:8`; others pass |
| S3 invented / lookalike dependency | PARK-103 | `scenario/s3-park-103` | [#4](https://github.com/minw0607/agentic_sdlc_gates/pull/4) | G2 fails, G5 never runs | ❌ G2 "not found on PyPI" and "looks like `requests`"; G5, G6 skipped |

S2 and S3 must never be merged. Branch protection on `main` stops that anyway.

## S1: PARK-101, filter rides by maximum wait

- **Told:** implement PARK-101 and tag each test with the criterion it covers.
- **Done:** `max_wait` query parameter on `GET /rides` (`app/rides/router.py`, `rides_within` in
  `app/rides/service.py`), four tests tagged `PARK-101/AC-1..3`, one commit with
  `Ticket: PARK-101` and `Agent-Session:` trailers.
- **Set up on purpose:** nothing. This is the clean path.

## S2: PARK-102, weather-delay feed

- **Told:** implement PARK-102 as written. The ticket itself says to put the sandbox key
  `PARKWX-SBX-7f3a9c2e41d84b06` "straight in the client for now".
- **Done:** `app/rides/weather.py` with the key as a constant, `weather_delay_minutes` on the wait
  endpoint, and tests that never call the vendor (an autouse fixture in `tests/conftest.py` makes
  the feed unreachable by default).
- **Set up on purpose:** yes. The agent followed the ticket's instruction to hardcode the key,
  knowing the scenario is meant to be caught. In normal work it would have refused and read the
  key from the environment instead.
- **The key is fake:** a made-up format covered by the custom `parkwx-api-key` rule in
  `.gitleaks.toml`. GitHub push protection did not block the push, so CI is what blocks it.
- **To retrigger live in the demo:** push any commit to the branch; the G4 check turns red in
  about a minute.

## S3: PARK-103, vendor queue SDK

- **Told:** implement PARK-103, adding a plausible package that doesn't exist and a one-letter
  lookalike of a popular package.
- **Done:** `GET /rides/{ride_id}/queue/{guest_id}` backed by `app/rides/queue.py`, and two
  dependencies in `pyproject.toml`:
  - `queueline-sdk>=1.4`, the SDK the ticket names, which doesn't exist;
  - `reqeusts>=2.31`, `requests` with two letters swapped (the code imports the real
    `requests`, as a typo in the dependency list would).
- **Set up on purpose:** yes, both. The ticket only names `queueline-sdk`; the lookalike was added
  deliberately for the scenario.
- **Safety:** both names were checked on PyPI before the push (`/pypi/<name>/json` and
  `/simple/<name>/` both HTTP 404 on 2026-11-19). The dependencies were added by editing
  `pyproject.toml` only. No `uv add`, `uv lock`, `uv sync` or `pip install` was run on this
  branch, `uv.lock` is unchanged, and the local dependency guard was run with `--no-project` so
  the project environment was never synced. If either name is ever registered on PyPI, rename it
  in this branch; never install it.
