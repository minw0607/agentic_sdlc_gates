from fastapi import APIRouter, HTTPException

from app.dining import service
from app.dining.models import Reservation, ReservationRequest

router = APIRouter(prefix="/dining", tags=["dining"])


@router.post("/reservations", status_code=201)
def create_reservation(req: ReservationRequest) -> Reservation:
    """Book a table. The time must fall within the restaurant's opening hours."""
    restaurant = service.get_restaurant(req.restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=404, detail=f"Restaurant {req.restaurant_id} not found")
    try:
        return service.create_reservation(req, restaurant)
    except service.ReservationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
