from datetime import datetime, time

from pydantic import BaseModel, Field, field_validator

MAX_ONLINE_PARTY = 8


class Restaurant(BaseModel):
    id: str
    name: str
    area: str
    opens: time
    closes: time
    deposit_per_guest: float


class ReservationRequest(BaseModel):
    restaurant_id: str
    guest_name: str = Field(min_length=1, max_length=80)
    party_size: int = Field(ge=1)
    reserved_for: datetime

    @field_validator("party_size")
    @classmethod
    def _bookable_online(cls, v: int) -> int:
        if v > MAX_ONLINE_PARTY:
            raise ValueError(
                f"Online booking is for parties of up to {MAX_ONLINE_PARTY}. "
                "For a larger party, please call the restaurant."
            )
        return v


class Reservation(BaseModel):
    id: str
    restaurant_id: str
    guest_name: str
    party_size: int
    reserved_for: datetime
    deposit: float
