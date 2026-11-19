import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_list_rides_returns_every_ride(client: TestClient) -> None:
    rides = client.get("/rides").json()
    assert len(rides) == 7
    assert {"id", "name", "area", "status", "wait_minutes"} <= rides[0].keys()


def test_ride_wait_for_open_ride(client: TestClient) -> None:
    resp = client.get("/rides/r-01/wait")
    assert resp.status_code == 200
    assert resp.json() == {"ride_id": "r-01", "status": "open", "wait_minutes": 45}


def test_ride_wait_for_closed_ride_has_no_wait(client: TestClient) -> None:
    body = client.get("/rides/r-06/wait").json()
    assert body["status"] == "closed"
    assert body["wait_minutes"] is None


def test_ride_wait_unknown_ride_is_404(client: TestClient) -> None:
    resp = client.get("/rides/r-99/wait")
    assert resp.status_code == 404
    assert "r-99" in resp.json()["detail"]


# --- PARK-101: filter rides by maximum wait ------------------------------------------------


@pytest.mark.ac("PARK-101/AC-1")
def test_max_wait_returns_open_rides_at_or_under_limit(client: TestClient) -> None:
    rides = client.get("/rides", params={"max_wait": 30}).json()
    assert {r["id"] for r in rides} == {"r-02", "r-03", "r-05", "r-07"}
    assert all(r["status"] == "open" and r["wait_minutes"] <= 30 for r in rides)


@pytest.mark.ac("PARK-101/AC-2")
def test_max_wait_zero_returns_no_wait_rides_and_never_closed(client: TestClient) -> None:
    rides = client.get("/rides", params={"max_wait": 0}).json()
    assert {r["id"] for r in rides} == {"r-03", "r-07"}
    assert "r-06" not in {r["id"] for r in client.get("/rides?max_wait=1000").json()}


@pytest.mark.ac("PARK-101/AC-3")
def test_without_max_wait_lists_every_ride(client: TestClient) -> None:
    assert len(client.get("/rides").json()) == 7


@pytest.mark.ac("PARK-101/AC-3")
def test_negative_max_wait_is_422(client: TestClient) -> None:
    assert client.get("/rides", params={"max_wait": -1}).status_code == 422
