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
    assert resp.json() == {
        "ride_id": "r-01",
        "status": "open",
        "wait_minutes": 45,
        "weather_delay_minutes": None,
    }


def test_ride_wait_for_closed_ride_has_no_wait(client: TestClient) -> None:
    body = client.get("/rides/r-06/wait").json()
    assert body["status"] == "closed"
    assert body["wait_minutes"] is None


def test_ride_wait_unknown_ride_is_404(client: TestClient) -> None:
    resp = client.get("/rides/r-99/wait")
    assert resp.status_code == 404
    assert "r-99" in resp.json()["detail"]
