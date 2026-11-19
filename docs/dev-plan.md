# agentic_sdlc_gates: development plan

**Version:** v0.1 (Nov 19, 2026) · **Build window:** 2 days · **Owner:** Min Wu · **Built with:** Claude Code

## 1. Purpose

A drop-in set of **release gates for AI-written code**, plus **controls on the coding agent itself**. AI agents write code quickly. These checks decide what is safe to merge and release, and the agent controls limit what the agent can reach while it works.

The first use is a 4–5 minute demo for an enterprise team running an "AI software factory": Jira stories, Claude Code or Cursor writing the code, GitHub pull requests, and GitHub Actions deciding what ships. The message is: *this is ready-made, it plugs into your existing tools, and it can be customized in days.*

It is also a public portfolio repo, alongside `axiom_agent_platform`, `llm_red_teaming`, `ai-governance-assurance` and `Regulus`.

**One-line pitch:** *Your agents write the code; these checks decide whether it ships, and keep the agent inside its lane while it works.*

## 2. Scope

**In scope (initial build)**

| # | Scenario | Gate(s) it shows |
|---|---|---|
| S1 | A clean change from Claude Code passes every check, with a trace from Jira story to acceptance criteria, tests and commit | Tests and coverage, traceability |
| S2 | The agent hardcodes a credential and the merge is blocked | Secret scan |
| S3 | The agent adds a dependency that doesn't exist or imitates a popular package, and the merge is blocked | Dependency guard |
| S4 | A Jira ticket carries hidden instructions. CI quarantines the ticket, and Claude Code's permission rules and hook stop the agent from reading secrets or calling out | Ticket screen, agent controls |
| S5 *(stretch)* | A change touches a high-risk path, so a named human must approve | High-risk path approval |

Every pull request also gets a **check summary**: which checks ran, what each found, and the trace from story to commit, as a job summary plus one pull-request comment.

**Out of scope for now:** a live Jira integration (tickets are Jira-shaped files), Cursor-side agent controls (the CI gates work the same whatever agent wrote the code), SAST/CodeQL, SBOM generation, container scanning, deployment, and any real client data or branding.

## 3. Decisions

| Topic | Decision | Why |
|---|---|---|
| Repo | `minw0607/agentic_sdlc_gates`, **public from day 1** | Portfolio repo. Branch protection and required checks are free on public repos. On a private repo they need a paid plan. All data is synthetic. |
| Language | Python 3.11, managed with `uv`, plus `ruff` and `pytest` | Same as Axiom |
| Sample service | A small FastAPI "theme park operations" API: ride wait times and dining reservations | Close to the buyer's domain, using only fictional names and synthetic data |
| Secret scan | **gitleaks CLI** (MIT), run directly in the workflow, plus a custom rule in `.gitleaks.toml` | The official `gitleaks-action@v2` needs a license key on organization-owned repos. The CLI doesn't, so the kit can drop into a client org. |
| Known vulnerabilities | **OSV-Scanner CLI** run in the workflow; fails on new findings | Avoids depending on SARIF upload and code scanning, which private repos need GitHub Advanced Security for |
| Fake and lookalike packages | Custom `gates/dep_guard.py` | No standard tool covers packages an agent invents, so this check is ours |
| Ticket screen | Custom `gates/ticket_screen.py`, with patterns adapted from Axiom's `injection_screen` and the `llm_red_teaming` indirect-injection templates | Reuse, not rebuild |
| Agent controls | `.claude/settings.json`: permission deny rules plus a `PreToolUse` guard hook (blocks) and a `PostToolUse` audit hook (logs) | A hook that blocks a call stops it before the permission rules are checked. Path-based deny rules don't cover a Bash subprocess that opens the file itself, so the hook must inspect Bash commands too. |
| Configuration | One `gates.yaml`: coverage floor, high-risk paths, approved packages, which checks fail and which only warn | Customizing for a client means editing configuration, not code |
| Reuse | The main workflow also exposes `workflow_call` | Another repo can adopt it with one `uses:` line, which is the "ready to go" proof |

## 4. Repository layout

```
agentic_sdlc_gates/
├── CLAUDE.md                     # conventions for Claude Code sessions
├── README.md                     # what, why, 60-second quick start, scenario table, demo GIF
├── gates.yaml                    # all thresholds and policies (configuration over code)
├── .gitleaks.toml                # default rules plus a custom rule for the demo credential format
├── .claude/
│   ├── settings.json             # permission deny rules plus hook registration (committed)
│   └── hooks/
│       ├── guard.py              # PreToolUse: blocks secret reads and network calls; returns deny with a reason
│       └── audit.py              # PostToolUse: appends every tool call to .agent-audit/tool_calls.jsonl
├── .github/
│   ├── workflows/factory-gates.yml   # all gates; triggers: pull_request and workflow_call
│   ├── CODEOWNERS                # S5: high-risk paths
│   └── pull_request_template.md  # requires a ticket key
├── app/                          # FastAPI service: rides/, dining/, payments/ (S5 high-risk)
├── tests/                        # pytest; each test tagged with the criteria it covers
├── tickets/                      # Jira-shaped JSON: PARK-101..PARK-105
├── gates/
│   ├── traceability.py           # ticket → criteria → passing tests → commit trailer
│   ├── dep_guard.py              # new dependencies must exist, look legitimate and be approved
│   ├── ticket_screen.py          # quarantines tickets with planted instructions
│   ├── summary.py                # job summary plus one PR comment that it updates
│   └── data/top_pypi.txt         # popular package names for the lookalike check
├── scripts/
│   ├── start_ticket.sh           # developer entry point: screen the ticket, then hand it to Claude Code
│   └── seed_scenarios.md         # exactly how each scenario branch was produced (honesty record)
└── docs/
    ├── dev-plan.md               # this file
    ├── ai-assisted-engineering.md # what Claude Code did, what changed after review, lessons
    └── demo-script.md            # recording beats and talk track
```

## 5. The sample service

Small on purpose: just enough real code for agents to change and tests to run.

- `GET /rides/{ride_id}/wait` returns the current wait in minutes from synthetic queue data
- `GET /rides?max_wait=30` lists rides under a wait threshold
- `POST /dining/reservations` creates a reservation, with party size limits and validation
- `app/payments/` holds a stub deposit calculator. It isn't wired to anything real; it exists to be a "high-risk path" for S5.
- Synthetic data lives in `app/data/*.json`. Ride and restaurant names are invented and generic.
- A baseline of about 10 tests passes at 80% coverage or more before any scenario starts.

## 6. The gates

All gates live in `.github/workflows/factory-gates.yml`. Each writes a result (`pass`, `fail`, `warn` or `not_evaluated`) to `reports/<gate>.json`. A gate that can't run records `not_evaluated`, never `pass` (fail closed, as in Axiom). `summary.py` runs last with `if: always()`.

| ID | Gate | Tool | Fails when | Job order |
|---|---|---|---|---|
| G1 | Ticket screen | `ticket_screen.py` | The PR's ticket contains planted instructions: hidden HTML comments, text addressed to an AI, "ignore previous", instructions to read secrets or contact URLs, or zero-width or full-width characters | First |
| G2 | Dependency guard | `dep_guard.py` | A new dependency in `pyproject.toml`: (a) doesn't exist on PyPI, (b) is within edit distance 2 of a top-PyPI name without being that name, (c) was first released under 30 days ago, or (d) isn't in `gates.yaml: approved_packages` (warn only) | Before any install |
| G3 | Known vulnerabilities | OSV-Scanner CLI on `uv.lock` | A new known vulnerability | After G2 |
| G4 | Secret scan | gitleaks CLI on the PR's commits | Any finding | In parallel |
| G5 | Tests and coverage | `pytest --cov`, with the floor taken from `gates.yaml` | Any failing test, or coverage below the floor | Needs G2 (**never install a dependency G2 rejected**) |
| G6 | Traceability | `traceability.py` | The PR title lacks a ticket key; the ticket file is missing; an acceptance criterion has no passing test; or a commit lacks a `Ticket:` trailer | After G5 |
| G7 *(S5)* | High-risk paths | `CODEOWNERS` plus branch protection that requires a code-owner review | A change touches `app/payments/**` or `.github/**` without the approver's review | GitHub-native |

**How traceability works**
- Tickets look like `tickets/PARK-101.json`: `{key, summary, description, acceptance_criteria:[{id, text}], risk}`.
- Tests declare what they cover with `@pytest.mark.ac("PARK-101/AC-1")`.
- A `conftest.py` plugin writes each marked test and its outcome to `reports/ac_map.json`. `traceability.py` joins that file to the ticket.

**The check summary**
- A table with one row per gate: result, a one-line reason, and a link to details.
- Then the trace: ticket key and title → each criterion → the tests covering it → commit SHAs → the agent session ID from the commit trailer, where one exists.
- It's posted as one PR comment, updated on every run (`pull-requests: write`), and also saved as `evidence.json`.

**The agent controls (local, Claude Code)**
- **Deny rules in `.claude/settings.json`:** `Read(./.env)`, `Read(./**/secrets/**)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`.
- **`guard.py` (PreToolUse):** catches what the deny rules miss.
  - Bash commands that touch `.env` or secrets (`cat`, `head`, `python -c open(...)`), outbound network calls (`curl`, `wget`, `nc`, `python -m http`, `requests.post`), and `git push --force`.
  - It returns `permissionDecision: "deny"` with a plain-language reason. Exit code 2 also blocks; **check which behavior your installed Claude Code version honors**, since some 2026 versions had bugs here.
- **`audit.py` (PostToolUse):** appends `{ts, session_id, tool, input_hash, decision}` to `.agent-audit/tool_calls.jsonl`, which is gitignored. A short excerpt is shown in the demo.
- **Unit tests for both hooks:** feed sample JSON on stdin and check the decision. Then the demo doesn't depend on the model falling for an injection, because most current models refuse obvious ones on their own.

## 7. Scenarios

Each scenario has a ticket, a branch produced by Claude Code, and a PR. `scripts/seed_scenarios.md` records exactly what Claude Code was told. S2 and S3 are deliberately set up to trigger a failure, and the README says so.

**S1: Clean change (PARK-101, "Filter rides by maximum wait")**
- **Ticket:** 3 acceptance criteria. One is the edge case where `max_wait=0` returns rides with no wait.
- **Agent run:** `scripts/start_ticket.sh PARK-101`, then Claude Code implements the change and writes tests tagged with each criterion.
- **Expected result:** every gate is green. The summary shows all 3 criteria covered, and the commit trailers carry `Ticket: PARK-101`.
- **Demo beat:** "This is what good looks like, and the evidence writes itself."

**S2: Hardcoded credential (PARK-102, "Add a weather-delay feed")**
- **Ticket:** says the vendor's sandbox key is `PARKWX-…`. It's a fake in a made-up format covered by the custom `.gitleaks.toml` rule.
- **Expected result:** G4 fails, naming the file and line. Every other gate passes.
- **Watch for:** use a made-up key format so GitHub's own push protection doesn't stop the push before CI runs. If it does, that's also a fine demo moment, but CI has to be the one shown blocking.
- **Demo beat:** "The agent did what the ticket said. The check caught what the ticket shouldn't have asked."

**S3: Invented or lookalike dependency (PARK-103, "Use the vendor queue SDK")**
- **Ticket:** names an SDK. The branch adds two dependencies: a plausible package that doesn't exist, and a one-letter lookalike of a popular package.
- **Expected result:** G2 fails with "not found on PyPI" and "looks like `requests`". G5 doesn't run, so nothing is installed.
- **Safety:** **at build time, confirm both names don't exist on PyPI.** If a lookalike does exist, pick another and never install it.
- **Demo beat:** "Agents invent package names. Attackers register them. Nothing gets installed until it passes."

**S4: Prompt injection from a ticket (PARK-104, "Dining reservations: add a party-size limit")**
- **Ticket:** a normal story, plus a hidden HTML comment telling the AI assistant to read `.env` and send it to `https://telemetry.example.invalid`. The repo has a `.env` with **dummy values only**.
- **Local, part a:** `start_ticket.sh PARK-104` runs the screen, which prints QUARANTINED with the matched lines, and stops.
- **Local, part b:** override the screen and hand the ticket to Claude Code. The guard hook blocks any attempt to read `.env` or call out, and Claude Code shows the reason. The audit log records the denied calls.
- **If the model ignores the injection on its own:** say so, then show the hook directly by asking Claude Code to `cat .env`. Either way the control is visible.
- **CI:** a PR referencing PARK-104 fails G1, even if the code itself is fine.
- **Demo beat:** "Least privilege for the agent, not just the code. And every tool call is on the record."

**S5 (stretch): High-risk path (PARK-105, "Deposit rounding fix in payments")**
- **Expected result:** every gate passes, but the merge stays blocked until `@minwu-ai`, set as code owner and collaborator, approves. The summary records who approved.
- **Watch for:** you can't approve your own PR, which is why the second account is the approver.

## 8. Day-by-day plan

**Day 0 (tonight, about 30 minutes)**
- [ ] Create the empty public repo `agentic_sdlc_gates` and clone it to a **local folder outside iCloud**.
- [ ] Put this file in `docs/dev-plan.md`, open Claude Code in the repo, and paste the kickoff prompt from section 12.
- [ ] Add `minwu-ai` as a collaborator (needed for S5).

**Day 1 (morning): foundation**
- [ ] Generate `CLAUDE.md` from sections 3–6, with the same conventions as Axiom.
- [ ] Build the sample service, synthetic data and baseline tests, and pass ruff and pytest locally.
- [ ] Write `gates.yaml` and the `conftest.py` criteria plugin.
- [ ] Write the tickets PARK-101 to PARK-105.
- **Done when:** `uv run pytest` passes, coverage ≥ 80%, and `reports/ac_map.json` is written.

**Day 1 (afternoon): gates and S1–S3**
- [ ] Write `factory-gates.yml` with G2–G6 and `summary.py`, and open a no-op PR to check it's green.
- [ ] Write `dep_guard.py` and its unit tests (exists, missing, lookalike, new, unapproved), mocking the PyPI calls.
- [ ] Write `traceability.py` and its unit tests.
- [ ] Turn on branch protection for `main`: G2–G6 required.
- [ ] Produce the S1, S2 and S3 branches with Claude Code, open the PRs, and confirm the expected results.
- **Done when:** three PRs show green, blocked by secret scan, and blocked by dependency guard, each with the summary comment.

**Day 2 (morning): agent controls and S4**
- [ ] Write `ticket_screen.py` and its unit tests: 10 planted patterns, plus 5 clean tickets that must pass.
- [ ] Write `.claude/settings.json`, `guard.py` and `audit.py`, plus the hook unit tests.
- [ ] Check in a live Claude Code session that the deny actually blocks on your installed version.
- [ ] Write `start_ticket.sh`.
- [ ] Run S4 parts a and b plus the CI PR.
- **Done when:** the S4 PR fails G1, and a recorded terminal session shows a blocked `.env` read with its audit entries.

**Day 2 (afternoon): polish, S5 if time, recording**
- [ ] S5 if Day 1 went smoothly: CODEOWNERS, required code-owner review, PR and approval.
- [ ] Write the README: the pitch, a scenario table linking each PR, a 60-second quick start, and the "adopt with one line" `workflow_call` snippet.
- [ ] Update `docs/ai-assisted-engineering.md`.
- [ ] Do a dry run, then record (section 9). Make one GIF for the README.
- **Done when:** a 4–5 minute recording exists, the README links every scenario PR, and a fresh clone passes all tests.

## 9. Recording plan (4–5 minutes)

1. **0:00–0:30 · The setup.** One diagram: Jira → agent → PR → gates → release. "Agents write code fast; these checks decide what ships."
2. **0:30–1:15 · S1.** The ticket, Claude Code working briefly (sped up), the green PR, and the summary's trace from story to tests to commit.
3. **1:15–1:50 · S2.** The red secret-scan check and the exact line.
4. **1:50–2:30 · S3.** The invented and lookalike packages blocked before install.
5. **2:30–3:45 · S4.** Ticket quarantined, then the override, the hook blocking the `.env` read, and the audit log. **This is the differentiator; slow down here.**
6. **3:45–4:15 · S5 or configuration.** Either the required approval, or `gates.yaml`: "customizing for your team means editing this file."
7. **4:15–4:45 · Close.** "Adopt with one line in your workflow. In your repos within days, tuned to your pipeline."

Keep S2 ready to trigger live: push one commit and the check turns red in about a minute.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| GitHub push protection blocks the S2 push | Use a made-up key format with a custom gitleaks rule |
| The model refuses the S4 injection, so nothing visibly gets blocked | The demo doesn't depend on it: show the hook directly, and rely on the hook unit tests |
| Hook deny behavior differs by Claude Code version | Return the JSON `permissionDecision: "deny"` and test it live on Day 2 morning |
| A lookalike package exists on PyPI and is malicious | G2 runs before any install; confirm names at build time; never `pip install` scenario packages locally |
| OSV or PyPI API outages make the demo flaky | Pre-recorded runs; G2 caches PyPI lookups in CI; a gate that can't run reports `not_evaluated` |
| Agent output varies between runs | Scenario branches are produced once, reviewed and committed; the recording uses those PRs |
| Overclaiming in the pitch | The README states what's illustrative, what's seeded, and that Cursor-side controls aren't covered yet |
| Client data or branding creeping in | `CLAUDE.md` "Do not" list; synthetic data only; generic names |

## 11. How it fits the portfolio

- **README "Built on" table**, like Axiom's: the ticket screen patterns come from `llm_red_teaming` and Axiom's guardrails; fail-closed results and the evidence idea come from Axiom; the control mapping comes from `ai-governance-assurance` (agentic AI checklist and testing guides).
- **Map each gate to OWASP Top 10 for LLM Applications 2026 and Agentic Applications IDs** in a short table: for example, prompt injection, supply chain, excessive agency and sensitive information disclosure. Check the IDs against the 2026 editions before publishing.
- **`docs/ai-assisted-engineering.md`** continues the pattern from Axiom: what was delegated, what review caught, and what was learned.

## 12. Kickoff prompt for Claude Code

Paste this as the first message in Claude Code, from the repo root, with this file at `docs/dev-plan.md`:

```
Read docs/dev-plan.md in full. It is the plan for this repo.

First, write CLAUDE.md for this repo from sections 3–6 of the plan: purpose, architecture
principles (configuration over code; fail closed: a gate that cannot run reports
not_evaluated, never pass), commands, conventions (Python 3.11, uv, ruff, pytest, typed
code, tests first for gates), and a "Do not" list: no real client names, branding or data;
no real secrets (dummy values only); never install a dependency that dep_guard rejected;
never pip install scenario packages locally.

Then do Day 1 morning from section 8: the sample service, synthetic data, baseline tests,
gates.yaml, the conftest criteria plugin, and tickets PARK-101..105. Stop when the Day 1
morning "done when" is met, show me the test and coverage output, and list anything in
the plan you think is wrong or risky before we start the gates.

Work in small commits with a "Ticket:" trailer where a ticket applies. Log what you did
in docs/ai-assisted-engineering.md.
```
