from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.rides import service
from app.rides.models import Ride, RideWait

router = APIRouter(prefix="/rides", tags=["rides"])


@router.get("")
def list_rides(
    max_wait: Annotated[int | None, Query(ge=0, description="Maximum wait in minutes")] = None,
) -> list[Ride]:
    """List rides with their current status and wait.

    With ``max_wait``, only open rides whose wait is at most that many minutes.
    """
    if max_wait is None:
        return service.all_rides()
    return service.rides_within(max_wait)


@router.get("/{ride_id}/wait")
def ride_wait(ride_id: str) -> RideWait:
    """Current wait in minutes for one ride. A closed ride has no wait."""
    ride = service.get_ride(ride_id)
    if ride is None:
        raise HTTPException(status_code=404, detail=f"Ride {ride_id} not found")
    return RideWait(ride_id=ride.id, status=ride.status, wait_minutes=ride.wait_minutes)
