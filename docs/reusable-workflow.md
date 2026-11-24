# Using the gates in another repository

Another repo runs the release gates by calling [`.github/workflows/gates.yml`](../.github/workflows/gates.yml)
with one `uses:` line. No gate code is copied into that repo.

## How it stays trustworthy

```
PR opened in the client repo
  └─ client's release-gates.yml  ──uses──▶  gates.yml in agentic_sdlc_gates @ pinned commit
        every job:
          gates-src/  ← gate CODE from agentic_sdlc_gates (the PR can't touch it)
          target/     ← the client's PR, treated as data
          policy/     ← gates.yaml, .gitleaks.toml, tickets/ from the client's BASE commit
        G1–G4, G6 run trusted code on that data
        G5 is split: tests_run executes the PR's tests (read-only token) → raw results
                     tests judges the raw results, running none of the PR's code
        Gates verdict → one PR comment + evidence.json → pass/block
```

- **Gate code** comes from this repo at a pinned version. The PR under review can't change it.
- **Policy** comes from what is already on the client's `main`. A PR can propose a change to
  `gates.yaml`, but it is still judged by the current rules, and the change takes effect only
  after a code owner approves and it merges. Until a client commits its own files,
  [`defaults/`](../defaults/) applies.
- **The PR's code** runs in one job only, and that job can't write a gate report. The most it
  can do is misreport its own test results, which is unavoidable when running someone's tests.
- **Gate steps run Python with `-P`**, so a `gates/` folder added by the PR can't replace the
  trusted gate code. `tests/test_reusable_workflow.py` checks this.

## Setting up a client repo

1. Copy [`examples/client/.github/workflows/release-gates.yml`](../examples/client/.github/workflows/release-gates.yml)
   into the repo and pin `uses:` to a full commit SHA of a release.
2. Commit a `gates.yaml` (start from [`defaults/gates.yaml`](../defaults/gates.yaml)) and,
   optionally, a `.gitleaks.toml`. Set `coverage.source` to the package folder.
3. Have `pytest` and `pytest-cov` in the project's dev dependencies (managed with uv, with a
   `uv.lock`). Tag tests with `@pytest.mark.ac("KEY-1/AC-1")` for traceability.
4. Protect `main` with branch protection or a ruleset:
   - require the check **`gates / Gates verdict`** (GitHub names it `<caller job> / <job>`);
   - require code-owner review, with CODEOWNERS covering `.github/`, `gates.yaml`,
     `.gitleaks.toml` and `tickets/`.
5. If the client's GitHub account restricts actions, allow `actions/checkout`,
   `actions/upload-artifact`, `actions/download-artifact`, `astral-sh/setup-uv` and this
   repo's workflow.

### Who controls the caller file?

A PR could edit `release-gates.yml` to call a look-alike workflow that also reports a passing
"Gates verdict". Two defences:

- **CODEOWNERS on `.github/`** (step 4): any such edit needs a named approver.
- **An organization ruleset that requires the workflow**: the workflow then runs from this
  repo and the client repo has no caller file to tamper with. This needs `on: pull_request`
  added to `gates.yml` and a GitHub plan with organization rulesets. Not set up yet.

### Where this repo lives

Public, so any repo can call it. A client that wants to control upgrades, or whose policy
forbids calling outside workflows, can mirror it into their own organization and change
`GATES_REPO` in the mirror.

## Releasing

`GATES_REF` in `gates.yml` falls back to the release the file belongs to. To release:

1. Set the fallback in `GATES_REF` to the new tag (e.g. `v1.0.0`) and merge.
2. Tag that merge commit with the same name.
3. Clients bump the pinned SHA. Dependabot (`package-ecosystem: github-actions`) does this
   for them.

A caller can also pass `gates-ref` to run a specific tag or commit.

## Options the gates read

Set by the workflow; each falls back to this repo's own layout, so `factory-gates.yml` and
local runs are unchanged.

| Variable | Default | Used for |
|---|---|---|
| `GATES_CONFIG` | `gates.yaml` | Policy file |
| `GATES_GITLEAKS_CONFIG` | `.gitleaks.toml` | Secret-scan rules |
| `GATES_TICKETS_DIR` | `tickets.dir` from policy | Ticket files |
| `GATES_RAW_DIR` | `reports/` | `junit.xml`, `coverage.json`, `ac_map.json`, `pytest_exit` |
| `GATES_REPORTS_DIR` | `reports/` | Gate reports |

`dep_guard.popular_names` resolves relative to this repo's folder, never the repo under review.

`python -m gates.tests_gate` still runs pytest and judges, as before. `... args` prints the
pytest coverage arguments, and `... judge` judges results produced elsewhere.

## Not covered yet

- **Python projects managed with uv only.** G2, G3 and G5 assume `pyproject.toml` and `uv.lock`.
- **This repo still uses `factory-gates.yml` for its own PRs.** Switching it to call `gates.yml`
  renames the required check to `gates / Gates verdict`, so branch protection has to change at
  the same time.
- **The package is still called `gates`.** It sits on `PYTHONPATH` next to the client's code in
  the tests job, so a client with its own `gates` module would clash. Renaming it is a later
  change.
- **The `.claude/` agent controls** still ship by copying them into each repo.
