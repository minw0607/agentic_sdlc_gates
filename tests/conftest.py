import urllib.error

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytest_plugins = ["gates.pytest_ac"]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def no_weather_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never call the weather vendor; by default its feed is unreachable."""

    def unreachable() -> dict[str, int]:
        raise urllib.error.URLError("vendor not reachable in tests")

    monkeypatch.setattr("app.rides.weather.fetch_delays", unreachable)
