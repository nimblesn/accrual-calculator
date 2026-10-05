from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from accrual.daycount.types import get_day_count
from accrual.models.bond import FixedRateBond
from accrual.models.period import AccrualPeriod
from accrual.rounding import RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod


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
    if start < bond.dated_date or end > bond.maturity_date or end < start:
        raise ValueError(f"range must lie within [{bond.dated_date}, {bond.maturity_date}]")
    periods = bond.schedule()
    results: list[DailyAccrual] = []
    day = start
    while day <= end:
        balance = accrued_balance(bond, face, periods, day)
        income_period = income_period_on(periods, day)
        daily = Decimal(0)
        if income_period is not None and bond.coupon_freq != 0:
            today = cumulative_accrual(bond, face, income_period, day)
            yesterday = cumulative_accrual(bond, face, income_period, day - timedelta(days=1))
            daily = RoundingPolicy.round_amount(today, bond.currency) - RoundingPolicy.round_amount(
                yesterday, bond.currency
            )
        results.append(
            DailyAccrual(
                on=day,
                accrued_cum=RoundingPolicy.round_amount(balance, bond.currency),
                accrued_daily=daily,
            )
        )
        day += timedelta(days=1)
    return results


def accrued_balance(
    bond: FixedRateBond, face: Decimal, periods: list[CouponPeriod], on: date
) -> Decimal:
    if bond.coupon_freq == 0:
        return Decimal(0)
    period = containing_period(periods, on)
    if period is None or period.start == on:
        return Decimal(0)
    return cumulative_accrual(bond, face, period, on)


def cumulative_accrual(
    bond: FixedRateBond, face: Decimal, period: CouponPeriod, on: date
) -> Decimal:
    if on == period.start:
        return Decimal(0)
    day_count = get_day_count(bond.day_count_code)
    accrual_period = AccrualPeriod(period.start, period.end, bond.coupon_freq)
    year_fraction = day_count.year_fraction(period.start, on, accrual_period)
    return face * bond.coupon_rate * year_fraction


def containing_period(periods: list[CouponPeriod], on: date) -> CouponPeriod | None:
    for period in periods:
        if period.start <= on < period.end:
            return period
    return None


def income_period_on(periods: list[CouponPeriod], on: date) -> CouponPeriod | None:
    for period in periods:
        if period.start < on <= period.end:
            return period
    return None
