from datetime import date
from decimal import Decimal

import pytest

from accrual.accrual.accrued_interest import DailyAccrual
from accrual.accrual.floating import Fixing, floating_accrued_on, floating_daily_accrual, rated_periods
from accrual.models.bond import FloatingRateBond

# Terms mirror samples/security_master.csv SAMPLE0004 and samples/floating_rate_index.csv.
SAMPLE0004 = FloatingRateBond(
    security_id="SAMPLE0004",
    currency="USD",
    issue_date=date(2024, 1, 10),
    dated_date=date(2024, 1, 10),
    maturity_date=date(2026, 1, 10),
    first_coupon_date=None,
    coupon_freq=4,
    day_count_code="ACT/360",
    end_of_month=False,
    redemption_price=Decimal("100"),
    index_name="SOFR",
    spread=Decimal("0.00350"),
    multiplier=Decimal("1"),
)

FIXINGS = [
    Fixing("SOFR", date(2024, 1, 10), Decimal("0.05300")),
    Fixing("SOFR", date(2024, 4, 10), Decimal("0.05250")),
    Fixing("SOFR", date(2024, 7, 10), Decimal("0.05100")),
]


def test_coupon_rate_is_index_times_multiplier_plus_spread() -> None:
    assert SAMPLE0004.coupon_rate(Decimal("0.05250")) == Decimal("0.05600")


def test_cap_and_floor_apply_to_total_coupon() -> None:
    capped = FloatingRateBond(**{**SAMPLE0004.__dict__, "cap": Decimal("0.05500")})
    floored = FloatingRateBond(**{**SAMPLE0004.__dict__, "floor": Decimal("0.06000")})
    assert capped.coupon_rate(Decimal("0.05250")) == Decimal("0.05500")
    assert floored.coupon_rate(Decimal("0.05250")) == Decimal("0.06000")


def test_each_period_uses_latest_fixing_on_or_before_its_start() -> None:
    rated = rated_periods(SAMPLE0004, FIXINGS)
    assert [rate for _, rate in rated[:3]] == [
        Decimal("0.05650"),
        Decimal("0.05600"),
        Decimal("0.05450"),
    ]


def test_unconfirmed_future_period_keeps_latest_known_rate() -> None:
    rated = rated_periods(SAMPLE0004, FIXINGS)
    assert rated[-1][1] == Decimal("0.05450")


def test_missing_fixing_before_first_period_raises() -> None:
    with pytest.raises(ValueError):
        rated_periods(SAMPLE0004, [Fixing("SOFR", date(2024, 4, 10), Decimal("0.05250"))])


def test_fixings_for_other_index_are_ignored() -> None:
    with pytest.raises(ValueError):
        rated_periods(SAMPLE0004, [Fixing("ESTR", date(2024, 1, 10), Decimal("0.01"))])


def test_accrual_matches_trade_sample_t0005() -> None:
    rated = rated_periods(SAMPLE0004, FIXINGS)
    assert floating_accrued_on(SAMPLE0004, Decimal("2000000"), rated, date(2024, 4, 12)) == Decimal("622.22")


def test_accrual_uses_latest_known_rate_in_unconfirmed_period() -> None:
    rated = rated_periods(SAMPLE0004, FIXINGS)
    assert floating_accrued_on(SAMPLE0004, Decimal("1000000"), rated, date(2024, 8, 10)) == Decimal("4693.06")


def test_daily_sum_over_one_period_equals_period_coupon() -> None:
    rated = rated_periods(SAMPLE0004, FIXINGS)
    days: list[DailyAccrual] = floating_daily_accrual(
        SAMPLE0004, Decimal("1000000"), rated, date(2024, 1, 10), date(2024, 4, 10)
    )
    assert sum(d.accrued_daily for d in days) == Decimal("14281.94")
    assert days[-1].accrued_cum == Decimal("0.00")
