from itertools import count

from app.data import load
from app.dining.models import Reservation, ReservationRequest, Restaurant
from app.payments.deposit import deposit_for


class ReservationError(ValueError):
    """The request is well formed but can't be booked."""


_ids = count(1)
_reservations: dict[str, Reservation] = {}


def get_restaurant(restaurant_id: str) -> Restaurant | None:
    match = next((r for r in load("restaurants") if r["id"] == restaurant_id), None)
    return Restaurant.model_validate(match) if match else None


def create_reservation(req: ReservationRequest, restaurant: Restaurant) -> Reservation:
    slot = req.reserved_for.time()
    if not restaurant.opens <= slot < restaurant.closes:
        raise ReservationError(
            f"{restaurant.name} is open {restaurant.opens:%H:%M}-{restaurant.closes:%H:%M}"
        )
    reservation = Reservation(
        id=f"res-{next(_ids):04d}",
        restaurant_id=restaurant.id,
        guest_name=req.guest_name,
        party_size=req.party_size,
        reserved_for=req.reserved_for,
        deposit=deposit_for(req.party_size, restaurant.deposit_per_guest),
    )
    _reservations[reservation.id] = reservation
    return reservation
