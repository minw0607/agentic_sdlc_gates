import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from gates.config import GATE_NAMES, GatesConfig, Mode, load_config, normalize_name
from gates.tickets import Ticket, load_ticket

ROOT = Path(__file__).resolve().parent.parent


def test_gates_yaml_is_valid() -> None:
    cfg = load_config(ROOT / "gates.yaml")
    assert set(cfg.gates) == set(GATE_NAMES)
    assert cfg.coverage.floor == 80
    assert "app/payments/**" in cfg.high_risk_paths
    assert cfg.dep_guard.unapproved is Mode.WARN


def test_config_rejects_unknown_and_missing_gates() -> None:
    raw = load_config(ROOT / "gates.yaml").model_dump()
    raw["gates"] = {"ticket_screen": {"mode": "fail"}, "typo_gate": {"mode": "fail"}}
    with pytest.raises(ValidationError, match="typo_gate"):
        GatesConfig.model_validate(raw)


def test_config_rejects_unknown_mode() -> None:
    raw = load_config(ROOT / "gates.yaml").model_dump()
    raw["gates"]["tests"] = {"mode": "maybe"}
    with pytest.raises(ValidationError):
        GatesConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("raw", "expected"), [("PyYAML", "pyyaml"), ("types_PyYAML", "types-pyyaml"), ("a.b", "a-b")]
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_every_ticket_loads_and_matches_its_filename() -> None:
    cfg = load_config(ROOT / "gates.yaml")
    files = sorted((ROOT / cfg.tickets.dir).glob("*.json"))
    assert [f.stem for f in files] == [f"PARK-10{i}" for i in range(1, 6)]
    for f in files:
        ticket = load_ticket(f.stem, ROOT / cfg.tickets.dir)
        assert re.fullmatch(cfg.tickets.key_pattern, ticket.key)


def test_criterion_ids_are_fully_qualified() -> None:
    ticket = load_ticket("PARK-101", ROOT / "tickets")
    assert ticket.criterion_ids() == ["PARK-101/AC-1", "PARK-101/AC-2", "PARK-101/AC-3"]


def test_ticket_rejects_duplicate_criteria() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        Ticket.model_validate(
            {
                "key": "PARK-1",
                "summary": "s",
                "description": "",
                "acceptance_criteria": [{"id": "AC-1", "text": "a"}, {"id": "AC-1", "text": "b"}],
                "risk": "low",
            }
        )


def test_load_ticket_rejects_mismatched_key(tmp_path: Path) -> None:
    src = (ROOT / "tickets" / "PARK-101.json").read_text()
    (tmp_path / "PARK-999.json").write_text(src)
    with pytest.raises(ValueError, match="expected PARK-999"):
        load_ticket("PARK-999", tmp_path)


def test_bare_yaml_off_means_off() -> None:
    import yaml

    raw = load_config(ROOT / "gates.yaml").model_dump(mode="json")
    raw["gates"]["tests"] = yaml.safe_load("{mode: off}")  # YAML reads this as False
    assert GatesConfig.model_validate(raw).gates["tests"].mode is Mode.OFF
