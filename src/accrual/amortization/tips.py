from collections.abc import Callable
from datetime import date
from decimal import Decimal

from accrual.accrual.tips import (
    RefCpi,
    index_ratio,
    interpolated_ref_cpi,
    tips_accrued_on,
    tips_daily_accrual,
    tips_projections,
)
from accrual.amortization.pass_through import projected_cash_amortization
from accrual.models.bond import TipsBond
from accrual.models.result import AmortizationResult


def tips_amortization(
    bond: TipsBond,
    par: Decimal,
    monthly_cpi: dict[tuple[int, int], Decimal],
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
    pay_date: Callable[[date], date] = lambda day: day,
) -> AmortizationResult:
    if not bond.dated_date <= settlement < end <= bond.maturity_date:
        raise ValueError("require dated_date <= settlement < end <= maturity_date")

    ref_cpi: RefCpi = lambda on: interpolated_ref_cpi(monthly_cpi, on)
    accrued_at_settlement = tips_accrued_on(bond, par, ref_cpi, settlement)
    adjusted_at_settlement = par * index_ratio(ref_cpi(settlement), bond.base_ref_cpi)
    projections = tips_projections(bond, par, ref_cpi, settlement, pay_date)

    def daily(start: date, stop: date):
        return tips_daily_accrual(bond, par, ref_cpi, start, stop)

    return projected_cash_amortization(
        currency=bond.currency,
        day_count_code=bond.day_count_code,
        coupon_freq=bond.coupon_freq,
        periods=bond.schedule(),
        daily=daily,
        accrued_at_settlement=accrued_at_settlement,
        face_amount=adjusted_at_settlement,
        clean_price=clean_price,
        transaction_cost=transaction_cost,
        projections=projections,
        settlement=settlement,
        end=end,
    )
