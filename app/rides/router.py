from fastapi import APIRouter, HTTPException

from app.rides import queue, service
from app.rides.models import QueuePosition, Ride, RideWait

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
    return RideWait(ride_id=ride.id, status=ride.status, wait_minutes=ride.wait_minutes)


@router.get("/{ride_id}/queue/{guest_id}")
def queue_position(ride_id: str, guest_id: str) -> QueuePosition:
    """The guest's place in the ride's virtual queue, from the vendor SDK."""
    if service.get_ride(ride_id) is None:
        raise HTTPException(status_code=404, detail=f"Ride {ride_id} not found")
    position = queue.position(ride_id, guest_id)
    if position is None:
        raise HTTPException(status_code=404, detail=f"Guest {guest_id} is not in the queue")
    return QueuePosition(ride_id=ride_id, guest_id=guest_id, position=position)
