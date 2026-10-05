from datetime import date
from decimal import Decimal

import pytest

from accrual.accrual.accrued_interest import accrued_interest_on, fixed_rate_daily_accrual
from accrual.models.bond import FixedRateBond

# Expected values below are hand-computed from the day count rules in the spec
# (see samples/trades.csv for the same figures).

SAMPLE0001 = FixedRateBond(
    security_id="SAMPLE0001",
    currency="USD",
    issue_date=date(2024, 1, 15),
    dated_date=date(2024, 1, 15),
    maturity_date=date(2029, 1, 15),
    first_coupon_date=date(2024, 7, 15),
    coupon_rate=Decimal("0.0425"),
    coupon_freq=2,
    day_count_code="30E/360",
    end_of_month=False,
)

SAMPLE0002_ZERO = FixedRateBond(
    security_id="SAMPLE0002",
    currency="JPY",
    issue_date=date(2024, 3, 1),
    dated_date=date(2024, 3, 1),
    maturity_date=date(2027, 3, 1),
    first_coupon_date=None,
    coupon_rate=Decimal("0"),
    coupon_freq=0,
    day_count_code="ACT/365",
    end_of_month=False,
)

SAMPLE0003_KRW = FixedRateBond(
    security_id="SAMPLE0003",
    currency="KRW",
    issue_date=date(2024, 2, 10),
    dated_date=date(2024, 2, 10),
    maturity_date=date(2026, 8, 10),
    first_coupon_date=date(2024, 5, 10),
    coupon_rate=Decimal("0.03"),
    coupon_freq=4,
    day_count_code="ACT/ACT",
    end_of_month=False,
)

JPY_SEMI = FixedRateBond(
    security_id="JPY_SEMI",
    currency="JPY",
    issue_date=date(2024, 1, 15),
    dated_date=date(2024, 1, 15),
    maturity_date=date(2029, 1, 15),
    first_coupon_date=date(2024, 7, 15),
    coupon_rate=Decimal("0.005"),
    coupon_freq=2,
    day_count_code="30E/360",
    end_of_month=False,
)


def test_accrued_matches_trade_sample_t0001() -> None:
    assert accrued_interest_on(SAMPLE0001, Decimal("1000000"), date(2024, 2, 22)) == Decimal("4368.06")


def test_accrued_matches_trade_sample_t0002() -> None:
    assert accrued_interest_on(SAMPLE0001, Decimal("500000"), date(2024, 3, 12)) == Decimal("3364.58")


def test_accrued_matches_trade_sample_t0004_isda() -> None:
    assert accrued_interest_on(SAMPLE0003_KRW, Decimal("500000000"), date(2024, 2, 16)) == Decimal("245901.64")


def test_accrued_is_zero_on_dated_date_and_coupon_date() -> None:
    assert accrued_interest_on(SAMPLE0001, Decimal("1000000"), date(2024, 1, 15)) == Decimal("0.00")
    assert accrued_interest_on(SAMPLE0001, Decimal("1000000"), date(2024, 7, 15)) == Decimal("0.00")


def test_jpy_is_rounded_to_whole_units() -> None:
    assert accrued_interest_on(JPY_SEMI, Decimal("10000000"), date(2024, 2, 15)) == Decimal("4167")


def test_zero_coupon_accrues_nothing() -> None:
    assert accrued_interest_on(SAMPLE0002_ZERO, Decimal("10000000"), date(2024, 6, 1)) == Decimal("0.00")


def test_daily_sum_over_one_coupon_period_equals_coupon() -> None:
    days = fixed_rate_daily_accrual(SAMPLE0001, Decimal("1000000"), date(2024, 1, 15), date(2024, 7, 15))
    assert sum(d.accrued_daily for d in days) == Decimal("21250.00")


def test_daily_sum_over_two_coupon_periods_equals_two_coupons() -> None:
    days = fixed_rate_daily_accrual(SAMPLE0001, Decimal("1000000"), date(2024, 1, 15), date(2025, 1, 15))
    assert sum(d.accrued_daily for d in days) == Decimal("42500.00")


def test_coupon_date_resets_balance_and_books_remaining_accrual() -> None:
    days = fixed_rate_daily_accrual(SAMPLE0001, Decimal("1000000"), date(2024, 7, 14), date(2024, 7, 15))
    day_before, coupon_day = days
    assert day_before.accrued_cum == Decimal("21131.94")
    assert coupon_day.accrued_cum == Decimal("0.00")
    assert coupon_day.accrued_daily == Decimal("118.06")


def test_daily_cumulative_matches_point_accrual() -> None:
    days = fixed_rate_daily_accrual(SAMPLE0001, Decimal("1000000"), date(2024, 2, 22), date(2024, 2, 22))
    assert days[0].accrued_cum == Decimal("4368.06")


def test_daily_range_outside_bond_life_raises() -> None:
    with pytest.raises(ValueError):
        fixed_rate_daily_accrual(SAMPLE0001, Decimal("1000000"), date(2024, 1, 1), date(2024, 1, 20))


def test_coupon_rate_validation() -> None:
    with pytest.raises(ValueError):
        FixedRateBond(
            security_id="BAD",
            currency="USD",
            issue_date=date(2024, 1, 15),
            dated_date=date(2024, 1, 15),
            maturity_date=date(2025, 1, 15),
            first_coupon_date=None,
            coupon_rate=Decimal("0.01"),
            coupon_freq=0,
            day_count_code="ACT/365",
            end_of_month=False,
        )
