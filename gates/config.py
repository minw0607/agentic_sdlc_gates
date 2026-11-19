"""Load and validate gates.yaml. Every gate reads its policy through here."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_PATH = Path("gates.yaml")
GATE_NAMES = ("ticket_screen", "dep_guard", "osv", "secret_scan", "tests", "traceability")


class Mode(StrEnum):
    FAIL = "fail"
    WARN = "warn"
    OFF = "off"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateSetting(_Strict):
    mode: Mode = Mode.FAIL


class Coverage(_Strict):
    floor: float = Field(ge=0, le=100)
    source: list[str]


class DepGuard(_Strict):
    lookalike_max_distance: int = Field(ge=0, le=5)
    min_age_days: int = Field(ge=0)
    unapproved: Mode = Mode.WARN
    popular_names: str


class Tickets(_Strict):
    dir: str
    key_pattern: str
    commit_trailer: str

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


def load_config(path: Path = DEFAULT_PATH) -> GatesConfig:
    with path.open(encoding="utf-8") as f:
        return GatesConfig.model_validate(yaml.safe_load(f))
