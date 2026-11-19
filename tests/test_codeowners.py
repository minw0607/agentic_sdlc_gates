from pathlib import Path

from gates.config import load_config

ROOT = Path(__file__).resolve().parent.parent


def _owned() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    for line in (ROOT / ".github" / "CODEOWNERS").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            pattern, *owners = line.split()
            rules[pattern] = owners
    return rules


def _as_codeowners(path: str) -> str:
    """gates.yaml's 'app/payments/**' is CODEOWNERS' '/app/payments/'."""
    return "/" + path.removesuffix("**")


def test_every_high_risk_path_has_a_code_owner() -> None:
    owned = _owned()
    for path in load_config(ROOT / "gates.yaml").high_risk_paths:
        assert owned.get(_as_codeowners(path)), f"{path} has no code owner in CODEOWNERS"


def test_codeowners_lists_only_high_risk_paths() -> None:
    expected = {_as_codeowners(p) for p in load_config(ROOT / "gates.yaml").high_risk_paths}
    assert set(_owned()) == expected
