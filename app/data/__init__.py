"""Synthetic park data. Every name here is invented."""

import json
from functools import cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent


@cache
def load(name: str) -> list[dict[str, Any]]:
    """Load one synthetic data file, e.g. ``load("rides")``."""
    with (DATA_DIR / f"{name}.json").open(encoding="utf-8") as f:
        data: list[dict[str, Any]] = json.load(f)
    return data
