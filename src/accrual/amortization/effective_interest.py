from datetime import date, timedelta
from decimal import Decimal

from accrual.accrual.accrued_interest import (
    accrued_balance,
    cumulative_accrual,
    fixed_rate_daily_accrual,
)
from accrual.amortization.eir_solver import solve_periodic_eir
from accrual.daycount.types import get_day_count
from accrual.models.bond import FixedRateBond
from accrual.models.period import AccrualPeriod
from accrual.models.result import AmortizationResult, AmortizationRow
from accrual.rounding import RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod


def fixed_rate_amortization(
    bond: FixedRateBond,
    face: Decimal,
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
) -> AmortizationResult:
    if bond.coupon_freq == 0:
        raise ValueError("zero coupon bonds use straight-line amortization")
    if not bond.dated_date <= settlement < end <= bond.maturity_date:
        raise ValueError("require dated_date <= settlement < end <= maturity_date")

    currency = bond.currency
    periods = bond.schedule()
    accrued_at_acquisition = RoundingPolicy.round_amount(
        accrued_balance(bond, face, periods, settlement), currency
    )
    acquisition = face * clean_price / 100 + transaction_cost
    dirty_at_acquisition = acquisition + accrued_at_acquisition
    redemption = face * bond.redemption_price / 100

    future = [p for p in periods if p.end > settlement]
    coupons = [cumulative_accrual(bond, face, p, p.end) for p in future]
    first_periods = _fraction(bond, settlement, future[0].end, future[0])

    flows = []
    for index, period in enumerate(future):
        amount = coupons[index]
        if index == len(future) - 1:
            amount += redemption
        flows.append((amount, first_periods + index))
    rate = solve_periodic_eir(flows, dirty_at_acquisition)

    period_starts = [dirty_at_acquisition]
    for index in range(len(future) - 1):
        growth = (1 + rate) ** first_periods if index == 0 else 1 + rate
        period_starts.append(period_starts[index] * growth - coupons[index])

    def dirty_at(on: date) -> Decimal:
        for index, period in enumerate(future):
            if period.start <= on < period.end:
                if index == 0:
                    base = dirty_at_acquisition
                    fraction = _fraction(bond, settlement, on, period)
                else:
                    base = period_starts[index]
                    fraction = _fraction(bond, period.start, on, period)
                return base * (1 + rate) ** fraction
        return Decimal(0)

    cash_on: dict[date, Decimal] = {p.end: coupons[i] for i, p in enumerate(future)}
    cash_on[bond.maturity_date] += redemption

    rows: list[AmortizationRow] = []
    for daily in fixed_rate_daily_accrual(bond, face, settlement + timedelta(days=1), end):
        on = daily.on
        dirty_now = dirty_at(on)
        dirty_before = dirty_at(on - timedelta(days=1))
        interest_income = (
            RoundingPolicy.round_amount(dirty_now, currency)
            - RoundingPolicy.round_amount(dirty_before, currency)
            + RoundingPolicy.round_amount(cash_on.get(on, Decimal(0)), currency)
        )
        if on == bond.maturity_date:
            amortized_cost = RoundingPolicy.round_amount(redemption, currency)
        else:
            amortized_cost = RoundingPolicy.round_amount(dirty_now, currency) - daily.accrued_cum
        rows.append(
            AmortizationRow(
                on=on,
                amortized_cost=amortized_cost,
                accrued_cum=daily.accrued_cum,
                accrued_daily=daily.accrued_daily,
                interest_income=interest_income,
                amortization=interest_income - daily.accrued_daily,
            )
        )

    return AmortizationResult(
        eir_periodic=rate,
        eir_annual=(1 + rate) ** bond.coupon_freq - 1,
        rows=rows,
    )


def _fraction(bond: FixedRateBond, start: date, on: date, period: CouponPeriod) -> Decimal:
    day_count = get_day_count(bond.day_count_code)
    accrual_period = AccrualPeriod(period.start, period.end, bond.coupon_freq)
    numerator = day_count.year_fraction(start, on, accrual_period)
    denominator = day_count.year_fraction(period.start, period.end, accrual_period)
    return numerator / denominator
