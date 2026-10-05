import dataclasses
from decimal import Decimal

import pytest

from accrual.models.money import Money


def test_accepts_decimal_amount() -> None:
    money = Money(Decimal("1.5"), "USD")
    assert money.amount == Decimal("1.5")
    assert money.currency == "USD"


def test_rejects_float_amount() -> None:
    with pytest.raises(TypeError):
        Money(1.5, "USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity")])
def test_rejects_non_finite_amount(amount: Decimal) -> None:
    with pytest.raises(ValueError):
        Money(amount, "USD")


@pytest.mark.parametrize("currency", ["usd", "US", "USDX", "1SD", ""])
def test_rejects_invalid_currency(currency: str) -> None:
    with pytest.raises(ValueError):
        Money(Decimal("1"), currency)


def test_add_and_sub_same_currency() -> None:
    a = Money(Decimal("10.25"), "USD")
    b = Money(Decimal("0.75"), "USD")
    assert a + b == Money(Decimal("11.00"), "USD")
    assert a - b == Money(Decimal("9.50"), "USD")


def test_add_different_currency_raises() -> None:
    with pytest.raises(ValueError):
        Money(Decimal("1"), "USD") + Money(Decimal("1"), "JPY")


def test_rounded_uses_currency_scale() -> None:
    assert Money(Decimal("2.675"), "USD").rounded() == Money(Decimal("2.68"), "USD")
    assert Money(Decimal("100.5"), "JPY").rounded() == Money(Decimal("101"), "JPY")


def test_is_immutable() -> None:
    money = Money(Decimal("1"), "USD")
    with pytest.raises(dataclasses.FrozenInstanceError):
        money.amount = Decimal("2")  # type: ignore[misc]
