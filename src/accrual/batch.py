import csv
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from accrual.accrual.accrued_interest import accrued_interest_on
from accrual.accrual.floating import floating_accrued_on, rated_periods
from accrual.accrual.pass_through import pass_through_accrued_on
from accrual.accrual.tips import RefCpi, inflation_compensation_on, interpolated_ref_cpi, tips_accrued_on
from accrual.amortization.effective_interest import fixed_rate_amortization, floating_amortization
from accrual.amortization.pass_through import pass_through_amortization
from accrual.amortization.straight_line import zero_coupon_amortization
from accrual.amortization.tips import tips_amortization
from accrual.disposal import Allocation
from accrual.io.loaders import TRADES, Inputs, Security, Trade, load_inputs
from accrual.io.parsing import ValidationError, ValidationFailed
from accrual.models.bond import TipsBond
from accrual.models.period import CashFlow, ProjectionVersion
from accrual.models.result import AmortizationResult, AmortizationRow
from accrual.rounding import RoundingPolicy

OUTPUT_COLUMNS = (
    "lot_id", "security_id", "currency", "date", "accrued_interest_cum", "accrued_interest_daily",
    "interest_income", "amortization", "amortized_cost", "eir", "inflation_accrual",
    "disposal_face", "disposal_clean_proceeds", "disposal_accrued_received",
    "disposal_transaction_cost", "derecognized_amortized_cost", "realized_gain_loss",
)


@dataclass(frozen=True)
class Disposal:
    face: Decimal
    clean_proceeds: Decimal
    accrued_received: Decimal
    transaction_cost: Decimal
    derecognized_amortized_cost: Decimal
    realized_gain_loss: Decimal


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
            lot_rows = _lot_rows(inputs, security, trade, warnings)
            inflation = _inflation_series(inputs, security, trade, [row for row, _ in lot_rows])
            for row, disposal in lot_rows:
                writer.writerow(_output_row(trade, security, row, disposal, inflation))
            lots += 1
            rows += len(lot_rows)
    return BatchReport(output=output, lots=lots, rows=rows, warnings=warnings)


def _lot_rows(
    inputs: Inputs,
    security: Security,
    trade: Trade,
    warnings: list[ValidationError],
) -> list[tuple[AmortizationRow, Disposal | None]]:
    calc_end = inputs.calc_end
    sold: list[Allocation] = [
        allocation
        for allocation in inputs.allocations.get(trade.lot_id, [])
        if allocation.sale.settlement_date <= calc_end
    ]
    faces = [trade.face_amount]
    for allocation in sold:
        faces.append(faces[-1] - allocation.face)

    rows: list[tuple[AmortizationRow, Disposal | None]] = []
    lower = trade.settlement_date
    for index, face in enumerate(faces):
        allocation = sold[index] if index < len(sold) else None
        upper = allocation.sale.settlement_date if allocation else calc_end
        result = _engine(inputs, security, trade, face, upper)
        for row in result.rows:
            if row.on <= lower:
                continue
            disposal = None
            if allocation is not None and row.on == upper:
                disposal = _disposal(row, allocation, face, currency=security.currency, warnings=warnings)
            rows.append((row, disposal))
        lower = upper
    return rows


def _disposal(
    row: AmortizationRow,
    allocation: Allocation,
    face: Decimal,
    currency: str,
    warnings: list[ValidationError],
) -> Disposal:
    sale = allocation.sale
    sold = allocation.face
    share = sold / face
    derecognized = RoundingPolicy.round_amount(row.amortized_cost * share, currency)
    clean = RoundingPolicy.round_amount(sale.clean_price * sold / 100, currency)
    calculated_accrued = RoundingPolicy.round_amount(row.accrued_cum * share, currency)
    if sale.accrued_received is not None and sale.accrued_received != calculated_accrued:
        warnings.append(ValidationError(
            TRADES, None, "accrued_interest_paid",
            f"{sale.trade_id}: received {sale.accrued_received} differs from calculated {calculated_accrued}",
        ))
    accrued = sale.accrued_received if sale.accrued_received is not None else calculated_accrued
    cost = RoundingPolicy.round_amount(sale.transaction_cost, currency)
    return Disposal(
        face=sold,
        clean_proceeds=clean,
        accrued_received=accrued,
        transaction_cost=cost,
        derecognized_amortized_cost=derecognized,
        realized_gain_loss=clean - cost - derecognized,
    )


def _engine(inputs: Inputs, security: Security, trade: Trade, face: Decimal, end: date) -> AmortizationResult:
    bond = security.bond
    price = trade.clean_price
    settlement = trade.settlement_date
    fraction = face / trade.face_amount
    cost = trade.transaction_cost * fraction
    if security.bond_type == "FIXED":
        if bond.coupon_freq == 0:
            return zero_coupon_amortization(bond, face, settlement, price, cost, end)
        return fixed_rate_amortization(bond, face, settlement, price, cost, end)
    if security.bond_type == "FLOATING":
        return floating_amortization(bond, face, inputs.fixings, settlement, price, cost, end)
    if security.bond_type in ("MBS", "ABS"):
        scaled_bond = replace(bond, original_face=bond.original_face * fraction)
        projections = [_scaled(version, fraction) for version in inputs.projections.get(security.security_id, [])]
        return pass_through_amortization(
            scaled_bond, inputs.pool_factors.get(security.security_id, []), projections,
            settlement, face, price, cost, end,
        )
    return tips_amortization(bond, face, _cpi_series(inputs, security), settlement, price, cost, end)


def _scaled(version: ProjectionVersion, fraction: Decimal) -> ProjectionVersion:
    flows = tuple(
        CashFlow(
            cash.pay_date,
            cash.principal * fraction,
            cash.interest * fraction,
        )
        for cash in version.flows
    )
    return replace(version, flows=flows)


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


def _inflation_series(
    inputs: Inputs, security: Security, trade: Trade, rows: list[AmortizationRow]
) -> dict[date, Decimal] | None:
    if security.bond_type != "TIPS":
        return None
    ref = _ref_cpi(inputs, security)
    return {
        row.on: inflation_compensation_on(security.bond, trade.face_amount, ref, trade.settlement_date, row.on)
        for row in rows
    }


def _output_row(
    trade: Trade,
    security: Security,
    row: AmortizationRow,
    disposal: Disposal | None,
    inflation: dict[date, Decimal] | None,
) -> list[str]:
    currency = security.currency
    base = [
        trade.lot_id,
        security.security_id,
        currency,
        row.on.isoformat(),
        _amount(row.accrued_cum, currency),
        _amount(row.accrued_daily, currency),
        _amount(row.interest_income, currency),
        _amount(row.amortization, currency),
        _amount(row.amortized_cost, currency),
        _rate(row.eir_periodic),
        _amount(inflation[row.on], currency) if inflation else "",
    ]
    if disposal is None:
        return base + [""] * 6
    return base + [
        _amount(disposal.face, currency),
        _amount(disposal.clean_proceeds, currency),
        _amount(disposal.accrued_received, currency),
        _amount(disposal.transaction_cost, currency),
        _amount(disposal.derecognized_amortized_cost, currency),
        _amount(disposal.realized_gain_loss, currency),
    ]


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
