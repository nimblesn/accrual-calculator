from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from accrual.accrual.accrued_interest import (
    DailyAccrual,
    RatedPeriod,
    accrued_balance_rated,
    daily_accrual_series,
)
from accrual.models.bond import FloatingRateBond
from accrual.rounding import RoundingPolicy


@dataclass(frozen=True)
class Fixing:
    index_name: str
    reset_date: date
    rate: Decimal


def index_rate_on(bond: FloatingRateBond, fixings: list[Fixing], on: date) -> Decimal:
    applicable = sorted(
        (f for f in fixings if f.index_name == bond.index_name and f.reset_date <= on),
        key=lambda f: f.reset_date,
    )
    if not applicable:
        raise ValueError(f"no {bond.index_name} fixing on or before {on}")
    return applicable[-1].rate


def rated_periods(bond: FloatingRateBond, fixings: list[Fixing]) -> list[RatedPeriod]:
    relevant = sorted(
        (f for f in fixings if f.index_name == bond.index_name), key=lambda f: f.reset_date
    )
    rated: list[RatedPeriod] = []
    for period in bond.schedule():
        applicable = [f for f in relevant if f.reset_date <= period.start]
        if not applicable:
            raise ValueError(f"no {bond.index_name} fixing on or before {period.start}")
        rated.append((period, bond.coupon_rate(applicable[-1].rate)))
    return rated


def floating_accrued_on(
    bond: FloatingRateBond, face: Decimal, rated: list[RatedPeriod], on: date
) -> Decimal:
    balance = accrued_balance_rated(rated, face, bond.day_count_code, bond.coupon_freq, on)
    return RoundingPolicy.round_amount(balance, bond.currency)


def floating_daily_accrual(
    bond: FloatingRateBond,
    face: Decimal,
    rated: list[RatedPeriod],
    start: date,
    end: date,
) -> list[DailyAccrual]:
    if start < bond.dated_date or end > bond.maturity_date or end < start:
        raise ValueError(f"range must lie within [{bond.dated_date}, {bond.maturity_date}]")
    return daily_accrual_series(
        rated, face, bond.currency, bond.day_count_code, bond.coupon_freq, start, end
    )
