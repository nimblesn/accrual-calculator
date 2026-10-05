from datetime import date, timedelta
from decimal import Decimal

from accrual.models.bond import FixedRateBond
from accrual.models.result import AmortizationResult, AmortizationRow
from accrual.rounding import RoundingPolicy


def zero_coupon_amortization(
    bond: FixedRateBond,
    face: Decimal,
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
) -> AmortizationResult:
    if bond.coupon_freq != 0:
        raise ValueError("straight-line amortization applies to zero coupon bonds only")
    if not bond.dated_date <= settlement < end <= bond.maturity_date:
        raise ValueError("require dated_date <= settlement < end <= maturity_date")

    currency = bond.currency
    acquisition_cost = RoundingPolicy.round_amount(
        face * clean_price / 100 + transaction_cost, currency
    )
    redemption = RoundingPolicy.round_amount(face * bond.redemption_price / 100, currency)
    total_days = (bond.maturity_date - settlement).days
    gain = redemption - acquisition_cost

    def cumulative(on: date) -> Decimal:
        elapsed = (on - settlement).days
        return RoundingPolicy.round_amount(gain * elapsed / total_days, currency)

    rows: list[AmortizationRow] = []
    day = settlement + timedelta(days=1)
    while day <= end:
        amortization = cumulative(day) - cumulative(day - timedelta(days=1))
        rows.append(
            AmortizationRow(
                on=day,
                amortized_cost=acquisition_cost + cumulative(day),
                accrued_cum=Decimal(0),
                accrued_daily=Decimal(0),
                interest_income=amortization,
                amortization=amortization,
            )
        )
        day += timedelta(days=1)
    return AmortizationResult(eir_periodic=None, eir_annual=None, rows=rows)
