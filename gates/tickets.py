"""Jira-shaped tickets stored as JSON files in tickets/."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AcceptanceCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^AC-\d+$")
    text: str = Field(min_length=1)


class Ticket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[A-Z][A-Z0-9]*-\d+$")
    summary: str = Field(min_length=1)
    description: str
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    risk: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def _unique_criteria(self) -> Ticket:
        ids = [c.id for c in self.acceptance_criteria]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.key}: duplicate acceptance criterion ids")
        return self

    def criterion_ids(self) -> list[str]:
        """Fully qualified ids as used in test markers, e.g. PARK-101/AC-1."""
        return [f"{self.key}/{c.id}" for c in self.acceptance_criteria]


def load_ticket(key: str, tickets_dir: Path = Path("tickets")) -> Ticket:
    path = tickets_dir / f"{key}.json"
    ticket = Ticket.model_validate_json(path.read_text(encoding="utf-8"))
    if ticket.key != key:
        raise ValueError(f"{path} holds ticket {ticket.key}, expected {key}")
    return ticket
