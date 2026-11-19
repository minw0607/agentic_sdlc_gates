import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.rides import weather


@pytest.mark.ac("PARK-102/AC-1")
def test_wait_includes_weather_delay_for_ride_area(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(weather, "fetch_delays", lambda: {"Starlight Plaza": 15})
    body = client.get("/rides/r-01/wait").json()
    assert body["wait_minutes"] == 45
    assert body["weather_delay_minutes"] == 15


@pytest.mark.ac("PARK-102/AC-2")
def test_wait_still_returned_when_feed_fails(client: TestClient) -> None:
    body = client.get("/rides/r-01/wait").json()  # conftest makes the feed unreachable
    assert body["wait_minutes"] == 45
    assert body["weather_delay_minutes"] is None


@pytest.mark.ac("PARK-102/AC-2")
def test_wait_still_returned_when_feed_times_out(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow() -> dict[str, int]:
        raise TimeoutError

    monkeypatch.setattr(weather, "fetch_delays", slow)
    assert client.get("/rides/r-02/wait").json()["weather_delay_minutes"] is None


def test_fetch_delays_parses_vendor_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # use the real fetch_delays, with urlopen faked
    seen: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float) -> io.BytesIO:
        seen["headers"], seen["timeout"] = dict(req.header_items()), timeout
        return io.BytesIO(json.dumps({"delays": {"Harbor Walk": "20"}}).encode())

    monkeypatch.setattr(weather.urllib.request, "urlopen", fake_urlopen)
    assert weather.fetch_delays() == {"Harbor Walk": 20}
    assert seen["timeout"] == weather.TIMEOUT_SECONDS
    assert "X-api-key" in seen["headers"]
