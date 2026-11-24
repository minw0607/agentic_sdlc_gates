"""Reservation deposits. A stub: nothing is charged.

Amounts are computed in decimal and rounded half up to the cent, so a half-cent total such as
$73.125 is charged as $73.13 (PARK-105).
"""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def deposit_for(party_size: int, per_guest: float, discount: float = 0.0) -> float:
    """Deposit in dollars for a party, after an optional fractional discount."""
    if party_size < 1:
        raise ValueError("party_size must be at least 1")
    if not 0.0 <= discount < 1.0:
        raise ValueError("discount must be in [0, 1)")
    # str() keeps the decimal value as written (15.0, 0.025), not its binary approximation.
    amount = party_size * Decimal(str(per_guest)) * (1 - Decimal(str(discount)))
    return float(amount.quantize(CENT, rounding=ROUND_HALF_UP))
