"""G1 ticket screen: quarantine tickets that carry instructions aimed at the AI.

Tickets are data. A coding agent reads them, so text in a ticket that addresses the AI, tries
to override its rules, asks it to read secrets or send data somewhere, asks it to hide what it
did, or hides itself from a human reader is a sign of a planted prompt injection.

Patterns are adapted from the Axiom platform's injection guardrail and tuned for tickets. It's
a pattern screen: cheap and explainable, easy to evade with rewording, so it sits in front of
the agent controls in `.claude/` rather than replacing them.

Two entry points:

- CI: ``python -m gates.ticket_screen`` screens the ticket named in the PR title
  (GATES_PR_TITLE) and writes reports/ticket_screen.json. The report names the field, line and
  pattern, never the matched text, so the PR comment doesn't repeat the injection.
- Local: ``python -m gates.ticket_screen PARK-104`` prints CLEAN or QUARANTINED with the matched
  lines, for a developer about to hand the ticket to an agent. Exit code 0 means clean, 3 means
  quarantined, 2 means the ticket couldn't be read.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass

from gates.config import GatesConfig, load_config, tickets_dir
from gates.report import CannotEvaluate, Finding, Outcome, Result, env, run_gate
from gates.tickets import Ticket, load_ticket
from gates.traceability import ticket_key

# Characters a reader cannot see: zero-width, bidirectional controls, Unicode tag characters.
INVISIBLE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)
# Full-width ASCII look-alikes (U+FF01..U+FF5E), used to slip words past a plain-text filter.
FULLWIDTH = re.compile("[\uff01-\uff5e]")

# Matched against a normalized line: invisible characters removed, NFKC-folded, casefolded.
PATTERNS: dict[str, re.Pattern[str]] = {
    # HTML comments, script tags and chat-template tokens a renderer hides from people.
    "hidden_markup": re.compile(r"<!--|<\s*(script|style)\b|<\|[a-z_]+\|>|\[/?(inst|system)\]"),
    # "Note to the AI coding assistant", "the assistant must ..."
    "addresses_the_ai": re.compile(
        r"\b(note|message|instructions?) (to|for) (the |any )?"
        r"(ai|assistant|model|llm|agent|claude)\b"
        r"|\b(ai|coding assistant|language model|llm|agent)s?\b[^.\n]{0,30}"
        r"\b(must|should|shall|needs? to)\b"
    ),
    # "Ignore all previous instructions", "disregard your rules"
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
        r"\b(instructions?|rules?|guidelines?|prompts?|directions?|polic(y|ies)|claude\.md)\b"
    ),
    # "You are now ...", "new instructions", "system prompt"
    "role_change": re.compile(
        r"\byou are now\b|\bfrom now on,? you\b|\bnew instructions?\b"
        r"|\b(system|developer) (prompt|message|instructions?)\b"
    ),
    # "Read the .env file", "print the credentials", "cat ~/.ssh/id_rsa"
    "reads_secrets": re.compile(
        r"\b(read|open|cat|print|dump|copy|show|list|access|load)\b[^.\n]{0,40}"
        r"(\.env\b|\bsecrets?\b|\bcredentials?\b|private keys?|ssh keys?|id_rsa|\.aws\b|\.netrc)"
    ),
    # "POST its full contents to https://..."
    "sends_data_out": re.compile(
        r"\b(post|send|upload|exfiltrate|forward|transmit|pipe|copy)\b[^.\n]{0,60}"
        r"\b(contents?|output|file|data|values?|secrets?|keys?|tokens?|credentials?|env)\b"
        r"[^.\n]{0,30}\bto\b[^.\n]{0,10}https?://"
    ),
    # "Do not mention it in your summary", "without telling the user"
    "conceals_from_user": re.compile(
        r"\b(do not|don't|never|without)\b (mention|tell|reveal|disclose|inform|report)\w*"
    ),
    # "Commit with --no-verify", "disable the guard hook", "skip the gates"
    "bypasses_controls": re.compile(
        r"--no-verify|\bgit push (-f|--force)\b"
        r"|\b(disable|turn off|remove|skip|bypass)\b[^.\n]{0,20}"
        r"\b(hooks?|guard|gates?|checks?|ci|branch protection|permissions?|deny rules?)\b"
    ),
}


@dataclass(frozen=True)
class Hit:
    field: str  # "summary", "description" or "AC-2"
    line: int  # 1-based line within that field
    pattern: str
    text: str  # the raw line; printed locally, never written to a CI report


def normalize(text: str) -> str:
    """Fold look-alike characters and case so trivial disguises still match."""
    return unicodedata.normalize("NFKC", INVISIBLE.sub("", text)).casefold()


def scan(text: str, field: str) -> list[Hit]:
    hits: list[Hit] = []
    for n, line in enumerate(text.split("\n"), 1):
        if INVISIBLE.search(line):
            hits.append(Hit(field, n, "invisible_characters", line))
        if FULLWIDTH.search(line):
            hits.append(Hit(field, n, "fullwidth_characters", line))
        folded = normalize(line)
        hits += [Hit(field, n, code, line) for code, p in PATTERNS.items() if p.search(folded)]
    return hits


def screen(ticket: Ticket) -> list[Hit]:
    """Every suspicious line in the parts of a ticket an agent reads."""
    hits = scan(ticket.summary, "summary") + scan(ticket.description, "description")
    for ac in ticket.acceptance_criteria:
        hits += scan(ac.text, ac.id)
    return hits


def judge(ticket: Ticket, path: str) -> Outcome:
    hits = screen(ticket)
    details: dict[str, object] = {
        "ticket": ticket.key,
        "hits": [{"field": h.field, "line": h.line, "pattern": h.pattern} for h in hits],
    }
    if not hits:
        return Outcome(
            result=Result.PASS,
            reason=f"{ticket.key}: no instructions aimed at the AI",
            details=details,
        )
    findings = [
        Finding(
            result=Result.FAIL,
            message=f"{ticket.key} {h.field} line {h.line}: {h.pattern.replace('_', ' ')}",
            file=path,
        )
        for h in hits
    ]
    codes = sorted({h.pattern for h in hits})
    return Outcome(
        result=Result.FAIL,
        reason=f"{ticket.key} quarantined: {', '.join(codes)}",
        findings=findings,
        details=details,
    )


def gate(cfg: GatesConfig) -> Outcome:
    key = ticket_key(env("GATES_PR_TITLE"), cfg.tickets.key_pattern)
    if key is None:
        # Traceability (G6) decides whether a PR without a ticket is allowed.
        return Outcome(result=Result.PASS, reason="No ticket in the PR title, nothing to screen")
    folder = tickets_dir(cfg)
    path = folder / f"{key}.json"
    if not path.exists():
        raise CannotEvaluate(f"ticket {key} not found in {folder}/")
    return judge(load_ticket(key, folder), f"{cfg.tickets.dir}/{key}.json")


# --- local use -------------------------------------------------------------------------------

CLEAN, QUARANTINED, UNREADABLE = 0, 3, 2


def local(key: str) -> int:
    try:
        cfg = load_config()
        ticket = load_ticket(key, tickets_dir(cfg))
    except Exception as e:
        print(f"Could not read ticket {key}: {e}", file=sys.stderr)
        return UNREADABLE
    hits = screen(ticket)
    if not hits:
        print(f"CLEAN: {key} has no instructions aimed at the AI.")
        return CLEAN
    print(f"QUARANTINED: {key} looks like it carries instructions aimed at the AI.")
    print("Do not hand this ticket to an agent until a person has reviewed it.\n")
    by_line: dict[tuple[str, int], list[Hit]] = {}
    for h in hits:
        by_line.setdefault((h.field, h.line), []).append(h)
    for (field, line), group in by_line.items():
        shown = group[0].text.strip()
        shown = shown if len(shown) <= 160 else shown[:157] + "..."
        print(f"  {field} line {line}: {', '.join(h.pattern for h in group)}")
        print(f"    {shown!r}")
    return QUARANTINED


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args:
        return local(args[0])
    return run_gate("ticket_screen", "G1", "Ticket screen", gate)


if __name__ == "__main__":
    sys.exit(main())
