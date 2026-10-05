from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from accrual.daycount.types import get_day_count
from accrual.models.bond import FixedRateBond
from accrual.models.period import AccrualPeriod
from accrual.rounding import RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod

RatedPeriod = tuple[CouponPeriod, Decimal]


@dataclass(frozen=True)
class DailyAccrual:
    on: date
    accrued_cum: Decimal
    accrued_daily: Decimal


def accrued_interest_on(bond: FixedRateBond, face: Decimal, on: date) -> Decimal:
    balance = accrued_balance(bond, face, bond.schedule(), on)
    return RoundingPolicy.round_amount(balance, bond.currency)


def fixed_rate_daily_accrual(
    bond: FixedRateBond, face: Decimal, start: date, end: date
) -> list[DailyAccrual]:
    _require_within_life(bond.dated_date, bond.maturity_date, start, end)
    rated = [(period, bond.coupon_rate) for period in bond.schedule()]
    return daily_accrual_series(
        rated, face, bond.currency, bond.day_count_code, bond.coupon_freq, start, end
    )


def accrued_balance(
    bond: FixedRateBond, face: Decimal, periods: list[CouponPeriod], on: date
) -> Decimal:
    rated = [(period, bond.coupon_rate) for period in periods]
    return accrued_balance_rated(rated, face, bond.day_count_code, bond.coupon_freq, on)


def cumulative_accrual(
    bond: FixedRateBond, face: Decimal, period: CouponPeriod, on: date
) -> Decimal:
    return cumulative_rated(face, bond.coupon_rate, bond.day_count_code, bond.coupon_freq, period, on)


def accrued_balance_rated(
    rated: Sequence[RatedPeriod],
    face: Decimal,
    day_count_code: str,
    coupon_freq: int,
    on: date,
) -> Decimal:
    if coupon_freq == 0:
        return Decimal(0)
    found = containing_rated(rated, on)
    if found is None or found[0].start == on:
        return Decimal(0)
    period, rate = found
    return cumulative_rated(face, rate, day_count_code, coupon_freq, period, on)


def daily_accrual_series(
    rated: Sequence[RatedPeriod],
    face: Decimal,
    currency: str,
    day_count_code: str,
    coupon_freq: int,
    start: date,
    end: date,
) -> list[DailyAccrual]:
    results: list[DailyAccrual] = []
    day = start
    while day <= end:
        balance = accrued_balance_rated(rated, face, day_count_code, coupon_freq, day)
        daily = Decimal(0)
        income = income_rated_on(rated, day)
        if income is not None and coupon_freq != 0:
            period, rate = income
            today = cumulative_rated(face, rate, day_count_code, coupon_freq, period, day)
            yesterday = cumulative_rated(
                face, rate, day_count_code, coupon_freq, period, day - timedelta(days=1)
            )
            daily = RoundingPolicy.round_amount(today, currency) - RoundingPolicy.round_amount(
                yesterday, currency
            )
        results.append(
            DailyAccrual(
                on=day,
                accrued_cum=RoundingPolicy.round_amount(balance, currency),
                accrued_daily=daily,
            )
        )
        day += timedelta(days=1)
    return results


def cumulative_rated(
    face: Decimal,
    rate: Decimal,
    day_count_code: str,
    coupon_freq: int,
    period: CouponPeriod,
    on: date,
) -> Decimal:
    if on == period.start:
        return Decimal(0)
    day_count = get_day_count(day_count_code)
    accrual_period = AccrualPeriod(period.start, period.end, coupon_freq)
    year_fraction = day_count.year_fraction(period.start, on, accrual_period)
    return face * rate * year_fraction


def containing_rated(rated: Sequence[RatedPeriod], on: date) -> RatedPeriod | None:
    for period, rate in rated:
        if period.start <= on < period.end:
            return period, rate
    return None


def income_rated_on(rated: Sequence[RatedPeriod], on: date) -> RatedPeriod | None:
    for period, rate in rated:
        if period.start < on <= period.end:
            return period, rate
    return None


def _require_within_life(dated: date, maturity: date, start: date, end: date) -> None:
    if start < dated or end > maturity or end < start:
        raise ValueError(f"range must lie within [{dated}, {maturity}]")
