from app.data import load
from app.rides.models import Ride


def all_rides() -> list[Ride]:
    return [Ride.model_validate(r) for r in load("rides")]


def rides_within(max_wait: int) -> list[Ride]:
    """Open rides whose current wait is ``max_wait`` minutes or less. Closed rides never match."""
    return [
        r
        for r in all_rides()
        if r.status == "open" and r.wait_minutes is not None and r.wait_minutes <= max_wait
    ]


def get_ride(ride_id: str) -> Ride | None:
    return next((r for r in all_rides() if r.id == ride_id), None)
