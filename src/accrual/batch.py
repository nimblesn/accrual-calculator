import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from accrual.accrual.floating import floating_accrued_on, rated_periods
from accrual.accrual.pass_through import pass_through_accrued_on
from accrual.accrual.accrued_interest import accrued_interest_on
from accrual.accrual.tips import RefCpi, inflation_compensation_on, interpolated_ref_cpi, tips_accrued_on
from accrual.amortization.effective_interest import fixed_rate_amortization, floating_amortization
from accrual.amortization.pass_through import pass_through_amortization
from accrual.amortization.straight_line import zero_coupon_amortization
from accrual.amortization.tips import tips_amortization
from accrual.io.loaders import TRADES, Inputs, Security, Trade, load_inputs
from accrual.io.parsing import ValidationError, ValidationFailed
from accrual.models.bond import TipsBond
from accrual.models.result import AmortizationResult
from accrual.rounding import RoundingPolicy

OUTPUT_COLUMNS = (
    "lot_id", "security_id", "currency", "date", "accrued_interest_cum", "accrued_interest_daily",
    "interest_income", "amortization", "amortized_cost", "eir", "inflation_accrual",
)


@dataclass(frozen=True)
class BatchReport:
    output: Path
    lots: int
    rows: int
    warnings: list[ValidationError]


def run_batch(input_dir: Path, output: Path, calc_end: date) -> BatchReport:
    inputs = load_inputs(input_dir, calc_end)
    warnings: list[ValidationError] = []
    lots = 0
    rows = 0
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        for trade in inputs.trades:
            security = inputs.securities[trade.security_id]
            warning = _accrued_warning(inputs, security, trade)
            if warning is not None:
                warnings.append(warning)
            result = _compute(inputs, security, trade)
            inflation = _inflation_series(inputs, security, trade, result)
            for row in result.rows:
                writer.writerow([
                    trade.lot_id,
                    security.security_id,
                    security.currency,
                    row.on.isoformat(),
                    _amount(row.accrued_cum, security.currency),
                    _amount(row.accrued_daily, security.currency),
                    _amount(row.interest_income, security.currency),
                    _amount(row.amortization, security.currency),
                    _amount(row.amortized_cost, security.currency),
                    _rate(row.eir_periodic),
                    _amount(inflation[row.on], security.currency) if inflation else "",
                ])
            lots += 1
            rows += len(result.rows)
    return BatchReport(output=output, lots=lots, rows=rows, warnings=warnings)


def _compute(inputs: Inputs, security: Security, trade: Trade) -> AmortizationResult:
    end = inputs.calc_end
    bond = security.bond
    face, price, cost = trade.face_amount, trade.clean_price, trade.transaction_cost
    settlement = trade.settlement_date
    if security.bond_type == "FIXED":
        if bond.coupon_freq == 0:
            return zero_coupon_amortization(bond, face, settlement, price, cost, end)
        return fixed_rate_amortization(bond, face, settlement, price, cost, end)
    if security.bond_type == "FLOATING":
        return floating_amortization(bond, face, inputs.fixings, settlement, price, cost, end)
    if security.bond_type in ("MBS", "ABS"):
        return pass_through_amortization(
            bond, inputs.pool_factors.get(security.security_id, []),
            inputs.projections.get(security.security_id, []),
            settlement, face, price, cost, end,
        )
    return tips_amortization(bond, face, _cpi_series(inputs, security), settlement, price, cost, end)


def _accrued_warning(inputs: Inputs, security: Security, trade: Trade) -> ValidationError | None:
    if trade.accrued_interest_paid is None:
        return None
    computed = _accrued_at_settlement(inputs, security, trade)
    if computed == trade.accrued_interest_paid:
        return None
    return ValidationError(
        TRADES, None, "accrued_interest_paid",
        f"{trade.lot_id}: paid {trade.accrued_interest_paid} differs from calculated {computed}",
    )


def _accrued_at_settlement(inputs: Inputs, security: Security, trade: Trade) -> Decimal:
    bond = security.bond
    settlement = trade.settlement_date
    if security.bond_type == "FIXED":
        return accrued_interest_on(bond, trade.face_amount, settlement)
    if security.bond_type == "FLOATING":
        rated = rated_periods(bond, inputs.fixings)
        return floating_accrued_on(bond, trade.face_amount, rated, settlement)
    if security.bond_type in ("MBS", "ABS"):
        return pass_through_accrued_on(bond, inputs.pool_factors.get(security.security_id, []), settlement)
    return tips_accrued_on(bond, trade.face_amount, _ref_cpi(inputs, security), settlement)


def _inflation_series(inputs: Inputs, security: Security, trade: Trade, result: AmortizationResult):
    if security.bond_type != "TIPS":
        return None
    bond: TipsBond = security.bond
    ref = _ref_cpi(inputs, security)
    return {
        row.on: inflation_compensation_on(bond, trade.face_amount, ref, trade.settlement_date, row.on)
        for row in result.rows
    }


def _cpi_series(inputs: Inputs, security: Security) -> dict[tuple[int, int], Decimal]:
    return inputs.cpi.get(security.cpi_index_name or "", {})


def _ref_cpi(inputs: Inputs, security: Security) -> RefCpi:
    series = _cpi_series(inputs, security)
    return lambda on: interpolated_ref_cpi(series, on)


def _amount(value: Decimal, currency: str) -> str:
    places = RoundingPolicy.decimal_places(currency)
    return format(value.quantize(Decimal(1).scaleb(-places)), "f")


def _rate(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.quantize(Decimal("1E-12")), "f")
