from collections.abc import Callable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from accrual.accrual.accrued_interest import containing_rated, cumulative_rated
from accrual.models.bond import TipsBond
from accrual.rounding import WORKING_PRECISION, RoundingPolicy

_INDEX_RATIO_QUANTUM = Decimal("1E-5")
RefCpi = Callable[[date], Decimal]


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
