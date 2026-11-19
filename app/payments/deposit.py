"""Reservation deposits. A stub: nothing is charged.

Known issue for scenario S5 (PARK-105): this uses float arithmetic and Python's
round(), which rounds half to even and is subject to binary representation error,
so some half-cent totals round down. Left as is on purpose until PARK-105.
"""


def deposit_for(party_size: int, per_guest: float, discount: float = 0.0) -> float:
    """Deposit in dollars for a party, after an optional fractional discount."""
    if party_size < 1:
        raise ValueError("party_size must be at least 1")
    if not 0.0 <= discount < 1.0:
        raise ValueError("discount must be in [0, 1)")
    return round(party_size * per_guest * (1 - discount), 2)
