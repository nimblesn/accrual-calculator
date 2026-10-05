import calendar
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from accrual.accrual.accrued_interest import (
    DailyAccrual,
    containing_rated,
    cumulative_rated,
    income_rated_on,
)
from accrual.models.bond import TipsBond
from accrual.models.period import CashFlow, ProjectionVersion
from accrual.rounding import WORKING_PRECISION, RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod

_INDEX_RATIO_QUANTUM = Decimal("1E-5")
RefCpi = Callable[[date], Decimal]


def _shift_months(year: int, month: int, delta: int) -> tuple[int, int]:
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def interpolated_ref_cpi(monthly_cpi: Mapping[tuple[int, int], Decimal], on: date) -> Decimal:
    def cpi(delta: int) -> Decimal:
        key = _shift_months(on.year, on.month, delta)
        if key not in monthly_cpi:
            raise ValueError(f"missing CPI for {key[0]:04d}-{key[1]:02d}")
        return monthly_cpi[key]

    start = cpi(-3)
    end = cpi(-2)
    days_in_month = calendar.monthrange(on.year, on.month)[1]
    with localcontext() as ctx:
        ctx.prec = WORKING_PRECISION
        interpolated = start + Decimal(on.day - 1) / Decimal(days_in_month) * (end - start)
        return interpolated.quantize(_INDEX_RATIO_QUANTUM, rounding=ROUND_HALF_UP)


def index_ratio(ref_cpi: Decimal, base_ref_cpi: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = WORKING_PRECISION
        return (ref_cpi / base_ref_cpi).quantize(_INDEX_RATIO_QUANTUM, rounding=ROUND_HALF_UP)


def tips_accrued_on(bond: TipsBond, par: Decimal, ref_cpi: RefCpi, on: date) -> Decimal:
    rated = [(period, bond.real_coupon_rate) for period in bond.schedule()]
    found = containing_rated(rated, on)
    if found is None or found[0].start == on:
        return Decimal(0)
    period, rate = found
    ratio = index_ratio(ref_cpi(on), bond.base_ref_cpi)
    amount = cumulative_rated(
        par * ratio, rate, bond.day_count_code, bond.coupon_freq, period, on
    )
    return RoundingPolicy.round_amount(amount, bond.currency)


def inflation_compensation_on(
    bond: TipsBond, par: Decimal, ref_cpi: RefCpi, base: date, on: date
) -> Decimal:
    ratio_on = index_ratio(ref_cpi(on), bond.base_ref_cpi)
    ratio_base = index_ratio(ref_cpi(base), bond.base_ref_cpi)
    return RoundingPolicy.round_amount(par * (ratio_on - ratio_base), bond.currency)


def maturity_redemption(bond: TipsBond, par: Decimal, ref_cpi: RefCpi) -> Decimal:
    adjusted = par * index_ratio(ref_cpi(bond.maturity_date), bond.base_ref_cpi)
    if bond.deflation_floor:
        adjusted = max(adjusted, par)
    return RoundingPolicy.round_amount(adjusted, bond.currency)


def tips_daily_accrual(
    bond: TipsBond,
    par: Decimal,
    ref_cpi: RefCpi,
    start: date,
    end: date,
) -> list[DailyAccrual]:
    if start < bond.dated_date or end > bond.maturity_date or end < start:
        raise ValueError(f"range must lie within [{bond.dated_date}, {bond.maturity_date}]")
    schedule = bond.schedule()
    rated = [(period, bond.real_coupon_rate) for period in schedule]
    results: list[DailyAccrual] = []
    day = start
    while day <= end:
        found = containing_rated(rated, day)
        balance = Decimal(0)
        if found is not None and found[0].start != day:
            period, rate = found
            balance = _index_linked(bond, par, ref_cpi, period, rate, day)
        daily = Decimal(0)
        income = income_rated_on(rated, day)
        if income is not None:
            period, rate = income
            today = _index_linked(bond, par, ref_cpi, period, rate, day)
            yesterday = _index_linked(bond, par, ref_cpi, period, rate, day - timedelta(days=1))
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


def _index_linked(
    bond: TipsBond,
    par: Decimal,
    ref_cpi: RefCpi,
    period: CouponPeriod,
    rate: Decimal,
    on: date,
) -> Decimal:
    if on == period.start:
        return Decimal(0)
    ratio = index_ratio(ref_cpi(on), bond.base_ref_cpi)
    return cumulative_rated(par * ratio, rate, bond.day_count_code, bond.coupon_freq, period, on)


def tips_projections(
    bond: TipsBond,
    par: Decimal,
    ref_cpi: RefCpi,
    settlement: date,
    pay_date: Callable[[date], date] = lambda day: day,
) -> list[ProjectionVersion]:
    versions: list[ProjectionVersion] = []
    reset = date(settlement.year, settlement.month, 1)
    schedule = bond.schedule()
    while reset < bond.maturity_date:
        ratio = index_ratio(ref_cpi(reset), bond.base_ref_cpi)
        adjusted = par * ratio
        redemption = max(adjusted, par) if bond.deflation_floor else adjusted
        flows: list[CashFlow] = []
        for period in schedule:
            if period.end <= reset:
                continue
            coupon = cumulative_rated(
                adjusted, bond.real_coupon_rate, bond.day_count_code, bond.coupon_freq, period, period.end
            )
            principal = redemption if period.end == bond.maturity_date else Decimal(0)
            flows.append(CashFlow(pay_date(period.end), principal, coupon))
        versions.append(ProjectionVersion(version=len(versions) + 1, effective_date=reset, flows=tuple(flows)))
        reset = _next_month_start(reset)
    return versions


def _next_month_start(value: date) -> date:
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return date(year, month, 1)
