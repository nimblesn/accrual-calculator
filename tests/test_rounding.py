from decimal import Decimal

import pytest

from accrual.rounding import RoundingPolicy


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("0.125"), "USD", Decimal("0.13")),
        (Decimal("2.675"), "USD", Decimal("2.68")),
        (Decimal("1.005"), "USD", Decimal("1.01")),
        (Decimal("-0.125"), "USD", Decimal("-0.13")),
        (Decimal("0.124"), "USD", Decimal("0.12")),
        (Decimal("0.5"), "JPY", Decimal("1")),
        (Decimal("1.5"), "JPY", Decimal("2")),
        (Decimal("-0.5"), "JPY", Decimal("-1")),
        (Decimal("2.4"), "JPY", Decimal("2")),
        (Decimal("245901.639"), "KRW", Decimal("245901.64")),
    ],
)
def test_round_amount_half_up(amount: Decimal, currency: str, expected: Decimal) -> None:
    assert RoundingPolicy.round_amount(amount, currency) == expected


def test_round_amount_keeps_currency_scale() -> None:
    assert str(RoundingPolicy.round_amount(Decimal("1"), "USD")) == "1.00"
    assert str(RoundingPolicy.round_amount(Decimal("1.2"), "JPY")) == "1"


def test_large_amount_does_not_hit_default_precision() -> None:
    amount = Decimal("123456789012345678901234.565")
    assert RoundingPolicy.round_amount(amount, "USD") == Decimal("123456789012345678901234.57")


@pytest.mark.parametrize(("currency", "places"), [("JPY", 0), ("USD", 2), ("KRW", 2), ("EUR", 2)])
def test_decimal_places(currency: str, places: int) -> None:
    assert RoundingPolicy.decimal_places(currency) == places
