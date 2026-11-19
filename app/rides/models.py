from typing import Literal

from pydantic import BaseModel


class Ride(BaseModel):
    id: str
    name: str
    area: str
    status: Literal["open", "closed"]
    wait_minutes: int | None


class RideWait(BaseModel):
    ride_id: str
    status: Literal["open", "closed"]
    wait_minutes: int | None
    weather_delay_minutes: int | None = None
