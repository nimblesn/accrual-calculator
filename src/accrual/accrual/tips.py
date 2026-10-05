import calendar
from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from accrual.accrual.accrued_interest import containing_rated, cumulative_rated
from accrual.models.bond import TipsBond
from accrual.rounding import WORKING_PRECISION, RoundingPolicy

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
