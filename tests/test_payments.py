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
