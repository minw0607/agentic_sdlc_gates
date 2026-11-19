import pytest

from app.payments.deposit import deposit_for


def test_deposit_is_party_size_times_rate() -> None:
    assert deposit_for(4, 15.0) == 60.0


def test_deposit_with_discount() -> None:
    assert deposit_for(2, 10.0, discount=0.25) == 15.0


@pytest.mark.parametrize("party_size", [0, -1])
def test_deposit_rejects_empty_party(party_size: int) -> None:
    with pytest.raises(ValueError, match="party_size"):
        deposit_for(party_size, 10.0)


@pytest.mark.parametrize("discount", [-0.1, 1.0])
def test_deposit_rejects_bad_discount(discount: float) -> None:
    with pytest.raises(ValueError, match="discount"):
        deposit_for(1, 10.0, discount=discount)


# --- PARK-105: deposits round half up to the cent ------------------------------------------


@pytest.mark.ac("PARK-105/AC-1")
@pytest.mark.parametrize(
    ("party_size", "per_guest", "discount", "expected"),
    [(5, 15.0, 0.025, 73.13), (1, 15.0, 0.025, 14.63), (3, 10.0, 0.125, 26.25)],
)
def test_deposit_rounds_half_up_to_the_cent(
    party_size: int, per_guest: float, discount: float, expected: float
) -> None:
    assert deposit_for(party_size, per_guest, discount=discount) == expected


@pytest.mark.ac("PARK-105/AC-2")
@pytest.mark.parametrize(
    ("party_size", "per_guest", "discount", "expected"),
    [(4, 15.0, 0.0, 60.0), (2, 10.0, 0.25, 15.0), (6, 12.5, 0.0, 75.0)],
)
def test_exact_deposits_are_unchanged(
    party_size: int, per_guest: float, discount: float, expected: float
) -> None:
    assert deposit_for(party_size, per_guest, discount=discount) == expected
