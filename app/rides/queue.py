"""Virtual-queue positions from the queue vendor's SDK."""

import requests
from queueline import QueueClient, QueueNotFound

_client = QueueClient(session=requests.Session())


def position(ride_id: str, guest_id: str) -> int | None:
    """The guest's 1-based place in the ride's virtual queue, or None if they aren't in it."""
    try:
        return int(_client.position(ride=ride_id, guest=guest_id))
    except QueueNotFound:
        return None
