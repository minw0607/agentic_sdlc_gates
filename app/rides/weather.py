"""Weather-delay feed from the weather vendor."""

import json
import urllib.error
import urllib.request

BASE_URL = "https://weather-vendor.example.invalid/v1/delays"
API_KEY = "PARKWX-SBX-7f3a9c2e41d84b06"
TIMEOUT_SECONDS = 2.0


def fetch_delays() -> dict[str, int]:
    """Delay in minutes per park area, as the vendor reports it."""
    req = urllib.request.Request(BASE_URL, headers={"X-Api-Key": API_KEY})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        data = json.load(resp)
    return {str(area): int(minutes) for area, minutes in data["delays"].items()}


def delay_for(area: str) -> int | None:
    """Weather delay for one area, or None if the feed fails, times out or has no entry."""
    try:
        return fetch_delays().get(area)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError):
        return None
