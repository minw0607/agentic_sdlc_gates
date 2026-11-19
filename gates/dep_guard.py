"""G2 dependency guard: new dependencies must exist, look legitimate, be established and approved.

Compares the dependencies declared in pyproject.toml on the PR against the base branch. For
each new one it checks, in order:

(a) it exists on PyPI;
(b) it is not a lookalike: within ``lookalike_max_distance`` edits of a popular package
    name without being that package (names shorter than ``lookalike_min_length`` skip this,
    because short real names sit close together);
(c) its first release is at least ``min_age_days`` old;
(d) it is on ``approved_packages`` (by default a warning, not a failure).

This runs before anything is installed and reads PyPI's JSON API only. A package that
fails here must never be installed, so the tests gate (G5) depends on this one.

Run in CI as ``python -m gates.dep_guard`` with GATES_BASE_REF set to the base commit.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gates.config import GatesConfig, Mode, normalize_name
from gates.report import CannotEvaluate, Finding, Outcome, Result, env, run_gate

PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
PYPI_URL = "https://pypi.org/pypi/{name}/json"


@dataclass(frozen=True)
class PackageInfo:
    exists: bool
    first_release: datetime | None = None


PyPILookup = Callable[[str], PackageInfo]


# --- parsing -------------------------------------------------------------------------------


def declared_dependencies(pyproject_text: str) -> dict[str, str]:
    """Map normalized name -> requirement string for every declared dependency.

    Covers [project] dependencies, optional-dependencies and [dependency-groups].
    """
    data = tomllib.loads(pyproject_text)
    project = data.get("project", {})
    specs: list[str] = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        specs.extend(group)
    for group in data.get("dependency-groups", {}).values():
        specs.extend(s for s in group if isinstance(s, str))  # skip {include-group = ...}
    out: dict[str, str] = {}
    for spec in specs:
        m = PEP508_NAME.match(spec)
        if m:
            out[normalize_name(m.group(1))] = spec.strip()
    return out


def new_dependencies(base_text: str | None, head_text: str) -> dict[str, str]:
    head = declared_dependencies(head_text)
    base = declared_dependencies(base_text) if base_text else {}
    return {name: spec for name, spec in sorted(head.items()) if name not in base}


# --- lookalikes ----------------------------------------------------------------------------


def edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance: insert, delete, substitute, swap neighbours."""
    if a == b:
        return 0
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def closest_popular(
    name: str, popular: Iterable[str], max_distance: int, min_length: int
) -> tuple[str, int] | None:
    """The nearest popular name within ``max_distance``, if ``name`` isn't itself popular."""
    popular_set = set(popular)
    if name in popular_set or len(name) < min_length:
        return None
    best: tuple[str, int] | None = None
    for p in popular_set:
        if abs(len(p) - len(name)) > max_distance:
            continue
        d = edit_distance(name, p)
        if d <= max_distance and (best is None or (d, p) < (best[1], best[0])):
            best = (p, d)
    return best


def load_popular(path: Path) -> list[str]:
    if not path.exists():
        raise CannotEvaluate(f"popular names file {path} not found")
    lines = path.read_text(encoding="utf-8").splitlines()
    return [normalize_name(n) for n in (ln.strip() for ln in lines) if n and not n.startswith("#")]


# --- PyPI ----------------------------------------------------------------------------------


def pypi_lookup(name: str, timeout: float = 10.0, attempts: int = 3) -> PackageInfo:
    """Look a package up on PyPI. Raises CannotEvaluate if PyPI can't be reached."""
    url = PYPI_URL.format(name=name)
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "agentic-sdlc-gates"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.load(resp)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return PackageInfo(exists=False)
            last_error = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_error = e
    else:
        raise CannotEvaluate(f"PyPI lookup for {name} failed: {last_error}")
    uploads = [
        datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00"))
        for files in data.get("releases", {}).values()
        for f in files
        if f.get("upload_time_iso_8601")
    ]
    return PackageInfo(exists=True, first_release=min(uploads) if uploads else None)


# --- the check -----------------------------------------------------------------------------


def check(
    new: dict[str, str],
    cfg: GatesConfig,
    popular: list[str],
    lookup: PyPILookup,
    now: datetime | None = None,
) -> Outcome:
    now = now or datetime.now(UTC)
    policy = cfg.dep_guard
    findings: list[Finding] = []
    rows: list[dict[str, str | int | None]] = []

    for name, spec in new.items():
        approved = name in cfg.approved_packages
        info = lookup(name)
        row: dict[str, str | int | None] = {"name": name, "spec": spec, "approved": int(approved)}
        if not info.exists:
            findings.append(Finding(result=Result.FAIL, message=f"{name}: not found on PyPI"))
        if not approved:
            near = closest_popular(
                name, popular, policy.lookalike_max_distance, policy.lookalike_min_length
            )
            if near:
                findings.append(
                    Finding(
                        result=Result.FAIL,
                        message=f"{name}: looks like `{near[0]}` ({near[1]} edit(s) away)",
                    )
                )
                row["looks_like"] = near[0]
        if info.exists:
            if info.first_release is None:
                findings.append(
                    Finding(result=Result.FAIL, message=f"{name}: has no released files on PyPI")
                )
            else:
                age = (now - info.first_release).days
                row["age_days"] = age
                if age < policy.min_age_days:
                    findings.append(
                        Finding(
                            result=Result.FAIL,
                            message=(
                                f"{name}: first released {age} day(s) ago "
                                f"(policy: at least {policy.min_age_days})"
                            ),
                        )
                    )
        if not approved and policy.unapproved is not Mode.OFF:
            sev = Result.FAIL if policy.unapproved is Mode.FAIL else Result.WARN
            findings.append(
                Finding(result=sev, message=f"{name}: not on approved_packages in gates.yaml")
            )
        rows.append(row)

    details = {"new_dependencies": rows}
    if not new:
        return Outcome(result=Result.PASS, reason="No new dependencies", details=details)
    failed = [f for f in findings if f.result is Result.FAIL]
    if failed:
        names = sorted({f.message.split(":")[0] for f in failed})
        return Outcome(
            result=Result.FAIL,
            reason=f"Blocked before install: {', '.join(names)}",
            findings=findings,
            details=details,
        )
    if findings:
        return Outcome(
            result=Result.WARN,
            reason=f"{len(new)} new dependency(ies) need review",
            findings=findings,
            details=details,
        )
    return Outcome(
        result=Result.PASS,
        reason=f"{len(new)} new dependency(ies) checked",
        findings=findings,
        details=details,
    )


def base_pyproject(base_ref: str) -> str | None:
    """pyproject.toml at the base commit, or None if it didn't exist there."""
    res = subprocess.run(
        ["git", "show", f"{base_ref}:pyproject.toml"], capture_output=True, text=True
    )
    if res.returncode == 0:
        return res.stdout
    if "does not exist" in res.stderr or "exists on disk, but not in" in res.stderr:
        return None
    raise CannotEvaluate(f"could not read base pyproject.toml: {res.stderr.strip()}")


def gate(cfg: GatesConfig) -> Outcome:
    base_ref = env("GATES_BASE_REF")
    head_path = Path("pyproject.toml")
    if not head_path.exists():
        raise CannotEvaluate("pyproject.toml not found")
    new = new_dependencies(base_pyproject(base_ref), head_path.read_text(encoding="utf-8"))
    popular = load_popular(Path(cfg.dep_guard.popular_names))
    return check(new, cfg, popular, pypi_lookup)


def main() -> int:
    return run_gate("dep_guard", "G2", "Dependency guard", gate)


if __name__ == "__main__":
    sys.exit(main())
