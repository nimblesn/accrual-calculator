from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from accrual.accrual.accrued_interest import DailyAccrual, accrued_balance_rated, daily_accrual_series
from accrual.accrual.pass_through import PoolFactor, period_balances
from accrual.amortization.eir_solver import present_value, solve_periodic_eir
from accrual.daycount.types import get_day_count
from accrual.models.bond import PassThroughBond
from accrual.models.period import AccrualPeriod, ProjectionVersion
from accrual.models.result import AmortizationResult, AmortizationRow
from accrual.rounding import RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod

_ONE_DAY = timedelta(days=1)
_UNIT_FACE = Decimal(1)
DailyFn = Callable[[date, date], list[DailyAccrual]]


def pass_through_amortization(
    bond: PassThroughBond,
    factors: list[PoolFactor],
    projections: list[ProjectionVersion],
    settlement: date,
    face_amount: Decimal,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
) -> AmortizationResult:
    if not bond.dated_date <= settlement < end <= bond.maturity_date:
        raise ValueError("require dated_date <= settlement < end <= maturity_date")
    rated = period_balances(bond, factors)
    accrued0 = RoundingPolicy.round_amount(
        accrued_balance_rated(rated, _UNIT_FACE, bond.day_count_code, bond.coupon_freq, settlement),
        bond.currency,
    )

    def daily(start: date, stop: date) -> list[DailyAccrual]:
        return daily_accrual_series(
            rated, _UNIT_FACE, bond.currency, bond.day_count_code, bond.coupon_freq, start, stop
        )

    return projected_cash_amortization(
        currency=bond.currency,
        day_count_code=bond.day_count_code,
        coupon_freq=bond.coupon_freq,
        periods=[period for period, _ in rated],
        daily=daily,
        accrued_at_settlement=accrued0,
        face_amount=face_amount,
        clean_price=clean_price,
        transaction_cost=transaction_cost,
        projections=projections,
        settlement=settlement,
        end=end,
    )


def projected_cash_amortization(
    *,
    currency: str,
    day_count_code: str,
    coupon_freq: int,
    periods: list[CouponPeriod],
    daily: DailyFn,
    accrued_at_settlement: Decimal,
    face_amount: Decimal,
    clean_price: Decimal,
    transaction_cost: Decimal,
    projections: list[ProjectionVersion],
    settlement: date,
    end: date,
) -> AmortizationResult:
    day_count = get_day_count(day_count_code)
    freq = coupon_freq
    versions = sorted(projections, key=lambda v: v.effective_date)
    dirty_at_acquisition = (
        face_amount * clean_price / 100 + transaction_cost + accrued_at_settlement
    )

    def active_flows(on: date) -> tuple:
        applicable = [v for v in versions if v.effective_date <= on]
        if not applicable:
            raise ValueError(f"no projected cash flows effective on or before {on}")
        return applicable[-1].flows

    def discounted(on: date, flows: tuple) -> list[tuple[Decimal, Decimal]]:
        period = _period_at(periods, on)
        accrual_period = AccrualPeriod(period.start, period.end, freq)
        out = []
        for cash in flows:
            if cash.pay_date > on:
                years = day_count.year_fraction(on, cash.pay_date, accrual_period)
                out.append((cash.total, years * freq))
        return out

    rate = solve_periodic_eir(discounted(settlement, active_flows(settlement)), dirty_at_acquisition)

    def dirty_at(on: date) -> Decimal:
        return present_value(discounted(on, active_flows(on)), rate)

    rows: list[AmortizationRow] = []
    for accrual in daily(settlement + _ONE_DAY, end):
        on = accrual.on
        previous = on - _ONE_DAY
        cash_on = sum(
            (cash.total for cash in active_flows(previous) if cash.pay_date == on), Decimal(0)
        )
        dirty_now = dirty_at(on)
        interest_income = (
            RoundingPolicy.round_amount(dirty_now, currency)
            - RoundingPolicy.round_amount(dirty_at(previous), currency)
            + RoundingPolicy.round_amount(cash_on, currency)
        )
        rows.append(
            AmortizationRow(
                on=on,
                amortized_cost=RoundingPolicy.round_amount(dirty_now, currency) - accrual.accrued_cum,
                accrued_cum=accrual.accrued_cum,
                accrued_daily=accrual.accrued_daily,
                interest_income=interest_income,
                amortization=interest_income - accrual.accrued_daily,
                eir_periodic=rate,
            )
        )

    return AmortizationResult(
        eir_periodic=rate,
        eir_annual=(1 + rate) ** freq - 1,
        rows=rows,
    )


def _period_at(periods: list[CouponPeriod], on: date) -> CouponPeriod:
    for period in periods:
        if period.start <= on < period.end:
            return period
    return periods[-1]
