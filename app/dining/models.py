from datetime import datetime, time

from pydantic import BaseModel, Field


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


class Reservation(BaseModel):
    id: str
    restaurant_id: str
    guest_name: str
    party_size: int
    reserved_for: datetime
    deposit: float
