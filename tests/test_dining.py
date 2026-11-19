from typing import Any

import pytest
from fastapi.testclient import TestClient


def _request(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "restaurant_id": "d-01",
        "guest_name": "Sample Guest",
        "party_size": 4,
        "reserved_for": "2026-12-01T18:30:00",
    }
    body.update(overrides)
    return body


def test_create_reservation(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request())
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"].startswith("res-")
    assert body["party_size"] == 4
    assert body["deposit"] == 40.0


def test_reservation_ids_are_unique(client: TestClient) -> None:
    a = client.post("/dining/reservations", json=_request()).json()
    b = client.post("/dining/reservations", json=_request()).json()
    assert a["id"] != b["id"]


def test_reservation_at_restaurant_without_deposit(client: TestClient) -> None:
    body = client.post("/dining/reservations", json=_request(restaurant_id="d-03")).json()
    assert body["deposit"] == 0.0


def test_party_size_must_be_positive(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request(party_size=0))
    assert resp.status_code == 422


def test_guest_name_required(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request(guest_name=""))
    assert resp.status_code == 422


def test_unknown_restaurant_is_404(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request(restaurant_id="d-99"))
    assert resp.status_code == 404


def test_reservation_outside_opening_hours_is_rejected(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request(reserved_for="2026-12-01T08:00:00"))
    assert resp.status_code == 422
    assert "open 11:00-22:00" in resp.json()["detail"]


def test_closing_time_is_exclusive(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request(reserved_for="2026-12-01T22:00:00"))
    assert resp.status_code == 422


# --- PARK-104: party-size limit ------------------------------------------------------------


@pytest.mark.ac("PARK-104/AC-1")
def test_party_over_eight_is_told_to_call(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request(party_size=9))
    assert resp.status_code == 422
    assert "please call the restaurant" in resp.json()["detail"][0]["msg"]


@pytest.mark.ac("PARK-104/AC-2")
def test_party_of_exactly_eight_books_online(client: TestClient) -> None:
    resp = client.post("/dining/reservations", json=_request(party_size=8))
    assert resp.status_code == 201
    assert resp.json()["party_size"] == 8
