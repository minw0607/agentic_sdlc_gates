import pytest
from fastapi.testclient import TestClient

from app.rides import queue


@pytest.mark.ac("PARK-103/AC-1")
def test_queue_position_from_sdk(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "position", lambda ride, guest: 12)
    body = client.get("/rides/r-01/queue/g-100").json()
    assert body == {"ride_id": "r-01", "guest_id": "g-100", "position": 12}


@pytest.mark.ac("PARK-103/AC-2")
def test_unknown_guest_is_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue, "position", lambda ride, guest: None)
    assert client.get("/rides/r-01/queue/g-999").status_code == 404
