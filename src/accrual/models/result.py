from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class AmortizationRow:
    on: date
    amortized_cost: Decimal
    accrued_cum: Decimal
    accrued_daily: Decimal
    interest_income: Decimal
    amortization: Decimal
    eir_periodic: Decimal | None


@dataclass(frozen=True)
class AmortizationResult:
    eir_periodic: Decimal | None
    eir_annual: Decimal | None
    rows: list[AmortizationRow]
