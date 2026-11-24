from fastapi import APIRouter, HTTPException

from app.rides import service, weather
from app.rides.models import Ride, RideWait

router = APIRouter(prefix="/rides", tags=["rides"])


@router.get("")
def list_rides() -> list[Ride]:
    """List every ride with its current status and wait."""
    return service.all_rides()


@router.get("/{ride_id}/wait")
def ride_wait(ride_id: str) -> RideWait:
    """Current wait in minutes for one ride. A closed ride has no wait."""
    ride = service.get_ride(ride_id)
    if ride is None:
        raise HTTPException(status_code=404, detail=f"Ride {ride_id} not found")
    return RideWait(
        ride_id=ride.id,
        status=ride.status,
        wait_minutes=ride.wait_minutes,
        weather_delay_minutes=weather.delay_for(ride.area),
    )
