"""G2 dependency guard: new dependencies must exist, look legitimate, be established and approved.

Compares the dependencies declared in pyproject.toml on the PR against the base branch. For
each new one it checks, in order:

(a) it exists on PyPI;
(b) it is not a lookalike: within ``lookalike_max_distance`` edits of a popular package
    name without being that package (names shorter than ``lookalike_min_length`` skip this,
    because short real names sit close together);
(c) its first release is at least ``min_age_days`` old;
(d) it is on ``approved_packages`` (by default a warning, not a failure).

It also compares uv.lock, which is what ``uv sync --frozen`` actually installs:

- a package new to the lockfile that no one declared (a dependency of a dependency) gets
  checks (a) to (c), but not (d);
- a package that installs from anywhere but PyPI (git, a URL, a path, another index) fails;
- a PyPI package whose files come from another host, or whose recorded file hashes were
  replaced for the same version, fails.

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
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from gates.config import DepGuard, GatesConfig, Mode, kit_path, normalize_name
from gates.report import CannotEvaluate, Finding, Outcome, Result, env, run_gate

PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)")
PYPI_URL = "https://pypi.org/pypi/{name}/json"
LOCKFILE = "uv.lock"
PYPI_INDEX = "https://pypi.org/simple"
PYPI_FILES_HOST = "files.pythonhosted.org"


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


# --- the lockfile --------------------------------------------------------------------------


@dataclass(frozen=True)
class LockedPackage:
    name: str
    version: str
    source: dict[str, str]
    hashes: frozenset[str]
    file_hosts: frozenset[str]

    @property
    def is_this_project(self) -> bool:
        return self.source.get("virtual") == "." or self.source.get("editable") == "."


@dataclass
class LockChanges:
    """What a PR changed in uv.lock: packages new to it, and problems found."""

    new: dict[str, str]  # normalized name -> version
    findings: list[Finding] = field(default_factory=list)


def locked_packages(lock_text: str) -> list[LockedPackage]:
    out = []
    for p in tomllib.loads(lock_text).get("package", []):
        files = [p["sdist"]] if isinstance(p.get("sdist"), dict) else []
        files += [w for w in p.get("wheels", []) if isinstance(w, dict)]
        out.append(
            LockedPackage(
                name=normalize_name(str(p.get("name", ""))),
                version=str(p.get("version", "")),
                source={str(k): str(v) for k, v in (p.get("source") or {}).items()},
                hashes=frozenset(str(f["hash"]) for f in files if f.get("hash")),
                file_hosts=frozenset(
                    urllib.parse.urlsplit(str(f["url"])).hostname or "?"
                    for f in files
                    if f.get("url")
                ),
            )
        )
    return out


def _source_problem(pkg: LockedPackage) -> str | None:
    if pkg.is_this_project or pkg.source.get("registry") == PYPI_INDEX:
        return None
    kind, value = next(iter(pkg.source.items()), ("an unknown source", ""))
    return f"installs from {kind} {value}".rstrip() + ", not PyPI"


def lock_changes(base_text: str | None, head_text: str) -> LockChanges:
    base = locked_packages(base_text) if base_text else []
    base_names = {p.name for p in base}
    base_by_version = {(p.name, p.version): p for p in base}
    base_sources = {(p.name, tuple(sorted(p.source.items()))) for p in base}
    changes = LockChanges(new={})
    for pkg in locked_packages(head_text):
        if pkg.is_this_project:
            continue
        if pkg.name not in base_names:
            changes.new.setdefault(pkg.name, pkg.version)
        problem = _source_problem(pkg)
        if problem and (pkg.name, tuple(sorted(pkg.source.items()))) not in base_sources:
            changes.findings.append(
                Finding(result=Result.FAIL, message=f"{pkg.name}: {problem}", file=LOCKFILE)
            )
        if problem is None and pkg.source.get("registry") == PYPI_INDEX:
            foreign = sorted(pkg.file_hosts - {PYPI_FILES_HOST})
            if foreign:
                changes.findings.append(
                    Finding(
                        result=Result.FAIL,
                        message=(
                            f"{pkg.name} {pkg.version}: downloads files from "
                            f"{', '.join(foreign)}, not PyPI"
                        ),
                        file=LOCKFILE,
                    )
                )
        old = base_by_version.get((pkg.name, pkg.version))
        # PyPI may add wheels to a release later, so new hashes are fine; a removed or
        # replaced one means the files for this version were swapped.
        if old and old.source == pkg.source and not old.hashes <= pkg.hashes:
            changes.findings.append(
                Finding(
                    result=Result.FAIL,
                    message=(
                        f"{pkg.name} {pkg.version}: file hashes changed in uv.lock "
                        "for the same version"
                    ),
                    file=LOCKFILE,
                )
            )
    return changes


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


def _package_findings(
    name: str,
    info: PackageInfo,
    approved: bool,
    popular: list[str],
    policy: DepGuard,
    now: datetime,
    row: dict[str, str | int | None],
) -> list[Finding]:
    """Checks (a) to (c) for one package. Approved packages skip the lookalike check."""
    findings: list[Finding] = []
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
    return findings


def check(
    new: dict[str, str],
    cfg: GatesConfig,
    popular: list[str],
    lookup: PyPILookup,
    now: datetime | None = None,
    lock: LockChanges | None = None,
) -> Outcome:
    now = now or datetime.now(UTC)
    policy = cfg.dep_guard
    findings: list[Finding] = list(lock.findings) if lock else []
    rows: list[dict[str, str | int | None]] = []

    for name, spec in new.items():
        approved = name in cfg.approved_packages
        row: dict[str, str | int | None] = {"name": name, "spec": spec, "approved": int(approved)}
        findings += _package_findings(name, lookup(name), approved, popular, policy, now, row)
        if not approved and policy.unapproved is not Mode.OFF:
            sev = Result.FAIL if policy.unapproved is Mode.FAIL else Result.WARN
            findings.append(
                Finding(result=sev, message=f"{name}: not on approved_packages in gates.yaml")
            )
        rows.append(row)

    # New to uv.lock but not declared: dependencies of dependencies. Nobody chose them, so
    # the approved list doesn't apply, but they must still exist, be established and not be
    # lookalikes.
    transitive = {n: v for n, v in (lock.new if lock else {}).items() if n not in new}
    for name, version in transitive.items():
        approved = name in cfg.approved_packages
        row = {"name": name, "spec": version, "approved": int(approved), "via": LOCKFILE}
        findings += _package_findings(name, lookup(name), approved, popular, policy, now, row)
        rows.append(row)

    details = {"new_dependencies": rows}
    failed = [f for f in findings if f.result is Result.FAIL]
    if failed:
        names = sorted({f.message.split(":")[0].split(" ")[0] for f in failed})
        return Outcome(
            result=Result.FAIL,
            reason=f"Blocked before install: {', '.join(names)}",
            findings=findings,
            details=details,
        )
    if not new and not transitive and not findings:
        return Outcome(result=Result.PASS, reason="No new dependencies", details=details)
    if findings:
        return Outcome(
            result=Result.WARN,
            reason=f"{len(new) + len(transitive)} new dependency(ies) need review",
            findings=findings,
            details=details,
        )
    parts = []
    if new:
        parts.append(f"{len(new)} new dependency(ies)")
    if transitive:
        parts.append(f"{len(transitive)} new package(s) in {LOCKFILE}")
    return Outcome(
        result=Result.PASS,
        reason=f"{' and '.join(parts)} checked",
        findings=findings,
        details=details,
    )


def base_file(base_ref: str, path: str) -> str | None:
    """A file at the base commit, or None if it didn't exist there."""
    res = subprocess.run(["git", "show", f"{base_ref}:{path}"], capture_output=True, text=True)
    if res.returncode == 0:
        return res.stdout
    if "does not exist" in res.stderr or "exists on disk, but not in" in res.stderr:
        return None
    raise CannotEvaluate(f"could not read base {path}: {res.stderr.strip()}")


def base_pyproject(base_ref: str) -> str | None:
    """pyproject.toml at the base commit, or None if it didn't exist there."""
    return base_file(base_ref, "pyproject.toml")


def gate(cfg: GatesConfig) -> Outcome:
    base_ref = env("GATES_BASE_REF")
    head_path = Path("pyproject.toml")
    if not head_path.exists():
        raise CannotEvaluate("pyproject.toml not found")
    new = new_dependencies(base_pyproject(base_ref), head_path.read_text(encoding="utf-8"))
    popular = load_popular(kit_path(cfg.dep_guard.popular_names))
    head_lock = Path(LOCKFILE)
    if head_lock.exists():
        lock = lock_changes(base_file(base_ref, LOCKFILE), head_lock.read_text(encoding="utf-8"))
    else:
        missing = Finding(
            result=Result.WARN, message=f"No {LOCKFILE}: only pyproject.toml was checked"
        )
        lock = LockChanges(new={}, findings=[missing])
    return check(new, cfg, popular, pypi_lookup, lock=lock)


def main() -> int:
    return run_gate("dep_guard", "G2", "Dependency guard", gate)


if __name__ == "__main__":
    sys.exit(main())
