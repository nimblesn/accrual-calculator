from datetime import date
from decimal import Decimal

import pytest

from accrual.daycount.conventions import (
    Actual360,
    Actual365Fixed,
    Actual366,
    ActualActIsda,
    ActualAfb,
    ActualTsy,
    NoLeapDay365,
    Thirty360BondBasis,
    Thirty360Eurobond,
)
from accrual.models.period import AccrualPeriod

ANY_PERIOD = AccrualPeriod(date(2024, 1, 1), date(2025, 1, 1), 2)


def assert_fraction(actual: Decimal, expected: Decimal) -> None:
    quantum = Decimal("1E-20")
    assert actual.quantize(quantum) == expected.quantize(quantum)


@pytest.mark.parametrize(
    ("convention", "start", "end", "expected_days"),
    [
        (Thirty360BondBasis(), date(2024, 2, 29), date(2024, 3, 31), 32),
        (Thirty360Eurobond(), date(2024, 2, 29), date(2024, 3, 31), 31),
        (Actual360(), date(2024, 2, 29), date(2024, 3, 31), 31),
        (Actual365Fixed(), date(2024, 2, 29), date(2024, 3, 31), 31),
        (Actual365Fixed(), date(2024, 2, 28), date(2024, 3, 1), 2),
        (NoLeapDay365(), date(2024, 2, 28), date(2024, 3, 1), 1),
    ],
)
def test_spec_5_4_day_counts(convention, start, end, expected_days) -> None:
    assert convention.day_count(start, end) == expected_days


def test_thirty_360_bond_basis_day31_handling() -> None:
    convention = Thirty360BondBasis()
    assert convention.day_count(date(2024, 1, 30), date(2024, 3, 31)) == 60
    assert convention.day_count(date(2024, 1, 31), date(2024, 3, 31)) == 60
    assert convention.day_count(date(2024, 1, 29), date(2024, 3, 31)) == 62


def test_thirty_360_eurobond_day31_handling() -> None:
    convention = Thirty360Eurobond()
    assert convention.day_count(date(2024, 1, 30), date(2024, 3, 31)) == 60
    assert convention.day_count(date(2024, 1, 29), date(2024, 3, 31)) == 61


def test_thirty_360_year_fraction_is_over_360() -> None:
    assert_fraction(
        Thirty360BondBasis().year_fraction(date(2024, 1, 15), date(2024, 7, 15), ANY_PERIOD),
        Decimal(180) / Decimal(360),
    )


def test_actual_365_year_fraction() -> None:
    assert_fraction(
        Actual365Fixed().year_fraction(date(2024, 2, 28), date(2024, 3, 1), ANY_PERIOD),
        Decimal(2) / Decimal(365),
    )


def test_actual_366_year_fraction() -> None:
    assert_fraction(
        Actual366().year_fraction(date(2024, 2, 28), date(2024, 3, 1), ANY_PERIOD),
        Decimal(2) / Decimal(366),
    )


def test_act_afb_stub_containing_leap_day_uses_366() -> None:
    assert_fraction(
        ActualAfb().year_fraction(date(2024, 2, 28), date(2024, 3, 1), ANY_PERIOD),
        Decimal(2) / Decimal(366),
    )


def test_act_afb_splits_whole_years_from_end() -> None:
    assert_fraction(
        ActualAfb().year_fraction(date(2023, 2, 10), date(2024, 3, 10), ANY_PERIOD),
        Decimal(1) + Decimal(28) / Decimal(365),
    )


def test_act_afb_exact_whole_years() -> None:
    assert_fraction(
        ActualAfb().year_fraction(date(2020, 6, 15), date(2024, 6, 15), ANY_PERIOD),
        Decimal(4),
    )


def test_act_tsy_uses_quasi_coupon_period() -> None:
    period = AccrualPeriod(date(2024, 1, 15), date(2024, 7, 15), 2)
    assert_fraction(
        ActualTsy().year_fraction(date(2024, 1, 15), date(2024, 3, 15), period),
        Decimal(60) / Decimal(364),
    )


def test_act_act_isda_splits_at_year_boundary() -> None:
    assert_fraction(
        ActualActIsda().year_fraction(date(2023, 12, 31), date(2024, 1, 1), ANY_PERIOD),
        Decimal(1) / Decimal(365),
    )


def test_act_act_isda_multi_year() -> None:
    assert_fraction(
        ActualActIsda().year_fraction(date(2023, 7, 1), date(2025, 1, 1), ANY_PERIOD),
        Decimal(184) / Decimal(365) + Decimal(1),
    )


def test_act_act_isda_leap_stub_uses_366() -> None:
    assert_fraction(
        ActualActIsda().year_fraction(date(2024, 2, 28), date(2024, 3, 1), ANY_PERIOD),
        Decimal(2) / Decimal(366),
    )


def test_no_leap_day_full_leap_year_is_one() -> None:
    assert_fraction(
        NoLeapDay365().year_fraction(date(2024, 1, 1), date(2025, 1, 1), ANY_PERIOD),
        Decimal(1),
    )


@pytest.mark.parametrize(
    "convention",
    [Thirty360BondBasis(), Actual365Fixed(), ActualAfb(), ActualActIsda(), NoLeapDay365()],
)
def test_same_start_and_end_is_zero(convention) -> None:
    assert convention.year_fraction(date(2024, 5, 5), date(2024, 5, 5), ANY_PERIOD) == 0


@pytest.mark.parametrize(
    "convention",
    [Thirty360BondBasis(), Actual365Fixed(), ActualAfb(), ActualActIsda(), ActualTsy()],
)
def test_reversed_interval_raises(convention) -> None:
    with pytest.raises(ValueError):
        convention.day_count(date(2024, 5, 5), date(2024, 5, 4))
