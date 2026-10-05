from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from accrual.accrual.accrued_interest import (
    DailyAccrual,
    RatedPeriod,
    accrued_balance_rated,
    daily_accrual_series,
)
from accrual.models.bond import PassThroughBond
from accrual.rounding import RoundingPolicy

_UNIT_FACE = Decimal(1)


@dataclass(frozen=True)
class PoolFactor:
    effective_date: date
    factor: Decimal


def period_balances(bond: PassThroughBond, factors: list[PoolFactor]) -> list[RatedPeriod]:
    ordered = sorted(factors, key=lambda f: f.effective_date)
    rated: list[RatedPeriod] = []
    for period in bond.schedule():
        applicable = [f for f in ordered if f.effective_date <= period.start]
        if not applicable:
            raise ValueError(f"no pool factor on or before {period.start}")
        balance = bond.original_face * applicable[-1].factor
        rated.append((period, balance * bond.coupon_rate))
    return rated


def pass_through_accrued_on(
    bond: PassThroughBond, factors: list[PoolFactor], on: date
) -> Decimal:
    rated = period_balances(bond, factors)
    balance = accrued_balance_rated(rated, _UNIT_FACE, bond.day_count_code, bond.coupon_freq, on)
    return RoundingPolicy.round_amount(balance, bond.currency)


def pass_through_daily_accrual(
    bond: PassThroughBond,
    factors: list[PoolFactor],
    start: date,
    end: date,
) -> list[DailyAccrual]:
    if start < bond.dated_date or end > bond.maturity_date or end < start:
        raise ValueError(f"range must lie within [{bond.dated_date}, {bond.maturity_date}]")
    rated = period_balances(bond, factors)
    return daily_accrual_series(
        rated, _UNIT_FACE, bond.currency, bond.day_count_code, bond.coupon_freq, start, end
    )
