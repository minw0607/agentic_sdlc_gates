"""Load and validate gates.yaml. Every gate reads its policy through here."""

from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_PATH = Path("gates.yaml")
# The kit's own folder (the parent of gates/). In the reusable workflow this is the trusted
# checkout of agentic_sdlc_gates, not the repo under review.
KIT_ROOT = Path(__file__).resolve().parent.parent
GATE_NAMES = ("ticket_screen", "dep_guard", "osv", "secret_scan", "tests", "traceability")


class Mode(StrEnum):
    FAIL = "fail"
    WARN = "warn"
    OFF = "off"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateSetting(_Strict):
    mode: Mode = Mode.FAIL

    @field_validator("mode", mode="before")
    @classmethod
    def _yaml_off(cls, v: object) -> object:
        # YAML 1.1 reads a bare `off` as False. Accept it rather than fail on a common slip.
        return "off" if v is False else v


class Coverage(_Strict):
    floor: float = Field(ge=0, le=100)
    source: list[str]


class DepGuard(_Strict):
    lookalike_max_distance: int = Field(ge=0, le=5)
    lookalike_min_length: int = Field(ge=1)
    min_age_days: int = Field(ge=0)
    unapproved: Mode = Mode.WARN
    popular_names: str


class Tickets(_Strict):
    dir: str
    key_pattern: str
    commit_trailer: str
    agent_session_trailer: str
    no_ticket_label: str

    @field_validator("key_pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        re.compile(v)
        return v


class GatesConfig(_Strict):
    version: int
    gates: dict[str, GateSetting]
    coverage: Coverage
    dep_guard: DepGuard
    approved_packages: list[str]
    high_risk_paths: list[str]
    tickets: Tickets

    @field_validator("gates")
    @classmethod
    def _known_gates(cls, v: dict[str, GateSetting]) -> dict[str, GateSetting]:
        unknown = set(v) - set(GATE_NAMES)
        missing = set(GATE_NAMES) - set(v)
        if unknown or missing:
            raise ValueError(f"unknown gates {sorted(unknown)}, missing gates {sorted(missing)}")
        return v

    @field_validator("approved_packages")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        return sorted({normalize_name(n) for n in v})


def normalize_name(name: str) -> str:
    """PEP 503 normalized package name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def config_path() -> Path:
    """gates.yaml, or GATES_CONFIG when set (the reusable workflow reads policy from the base
    commit of the repo under review and points this at it)."""
    return Path(os.environ.get("GATES_CONFIG") or DEFAULT_PATH)


def load_config(path: Path | None = None) -> GatesConfig:
    with (path or config_path()).open(encoding="utf-8") as f:
        return GatesConfig.model_validate(yaml.safe_load(f))


def tickets_dir(cfg: GatesConfig) -> Path:
    """Where tickets are read from: GATES_TICKETS_DIR when set, else ``tickets.dir``."""
    return Path(os.environ.get("GATES_TICKETS_DIR") or cfg.tickets.dir)


def raw_dir() -> Path:
    """Where raw test results (junit.xml, coverage.json, ac_map.json) live: GATES_RAW_DIR when
    set, else reports/."""
    return Path(os.environ.get("GATES_RAW_DIR") or "reports")


def kit_path(path: str) -> Path:
    """A data file that ships with the kit. Relative paths resolve against the kit's folder,
    never the current directory, so the repo under review can't substitute its own copy."""
    p = Path(path)
    return p if p.is_absolute() else KIT_ROOT / p
