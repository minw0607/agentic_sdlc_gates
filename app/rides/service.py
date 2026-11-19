from app.data import load
from app.rides.models import Ride


def all_rides() -> list[Ride]:
    return [Ride.model_validate(r) for r in load("rides")]


def get_ride(ride_id: str) -> Ride | None:
    return next((r for r in all_rides() if r.id == ride_id), None)
