import csv
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

from accrual.accrual.accrued_interest import accrued_interest_on
from accrual.accrual.floating import floating_accrued_on, rated_periods
from accrual.accrual.pass_through import pass_through_accrued_on
from accrual.accrual.tips import RefCpi, inflation_compensation_on, interpolated_ref_cpi, tips_accrued_on
from accrual.amortization.effective_interest import OpeningState, fixed_rate_amortization, floating_amortization
from accrual.amortization.pass_through import pass_through_amortization
from accrual.amortization.straight_line import zero_coupon_amortization
from accrual.amortization.tips import tips_amortization
from accrual.calendar import adjust_payment_date, cash_dates
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
    snapshot: Path | None = None
    snapshot_rows: int = 0
    missing_snapshot_dates: tuple[date, ...] = ()


CASH_SCHEDULE_COLUMNS = (
    "security_id", "contract_pay_date", "cash_pay_date", "business_day_convention", "calendar_id",
)


def run_batch(
    input_dir: Path,
    output: Path,
    calc_end: date,
    snapshot_dates: tuple[date, ...] = (),
) -> BatchReport:
    inputs = load_inputs(input_dir, calc_end)
    warnings: list[ValidationError] = []
    lots = 0
    rows = 0
    snapshot_path = output.parent / "snapshot.csv" if snapshot_dates else None
    wanted = set(snapshot_dates)
    seen_dates: set[date] = set()
    snapshot_rows = 0
    _write_cash_schedule(inputs, output.parent / "cash_schedule.csv")
    with ExitStack() as stack:
        handle = stack.enter_context(output.open("w", encoding="utf-8", newline=""))
        writer = csv.writer(handle)
        writer.writerow(OUTPUT_COLUMNS)
        snapshot_writer = None
        if snapshot_path is not None:
            snapshot_handle = stack.enter_context(snapshot_path.open("w", encoding="utf-8", newline=""))
            snapshot_writer = csv.writer(snapshot_handle)
            snapshot_writer.writerow(OUTPUT_COLUMNS)
        for trade in inputs.trades:
            security = inputs.securities[trade.security_id]
            warning = _accrued_warning(inputs, security, trade)
            if warning is not None:
                warnings.append(warning)
            if trade.opening is not None:
                warnings.extend(_opening_warnings(inputs, security, trade))
            lot_rows = _lot_rows(inputs, security, trade, warnings)
            inflation = _inflation_series(inputs, security, trade, [row for row, _ in lot_rows])
            for row, disposal in lot_rows:
                line = _output_row(trade, security, row, disposal, inflation)
                writer.writerow(line)
                if row.on in wanted:
                    seen_dates.add(row.on)
                    if snapshot_writer is not None:
                        snapshot_writer.writerow(line)
                        snapshot_rows += 1
            lots += 1
            rows += len(lot_rows)
    missing = tuple(sorted(wanted - seen_dates))
    return BatchReport(
        output=output, lots=lots, rows=rows, warnings=warnings,
        snapshot=snapshot_path, snapshot_rows=snapshot_rows, missing_snapshot_dates=missing,
    )


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
    lower = _start(trade)
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


def _write_cash_schedule(inputs: Inputs, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CASH_SCHEDULE_COLUMNS)
        for security in inputs.securities.values():
            contract = _contract_pay_dates(inputs, security)
            for day, cash_day in cash_dates(security, inputs.holidays, contract):
                writer.writerow([
                    security.security_id,
                    day.isoformat(),
                    cash_day.isoformat(),
                    security.business_day_convention or "",
                    security.calendar_id or "",
                ])


def _contract_pay_dates(inputs: Inputs, security: Security) -> list[date]:
    if security.bond_type in ("MBS", "ABS"):
        versions = inputs.projections.get(security.security_id, [])
        if not versions:
            return []
        latest = max(versions, key=lambda version: version.version)
        return sorted({cash.pay_date for cash in latest.flows})
    return [period.end for period in security.bond.schedule()]


def _start(trade: Trade) -> date:
    return trade.opening.as_of if trade.opening is not None else trade.settlement_date


def _engine(inputs: Inputs, security: Security, trade: Trade, face: Decimal, end: date) -> AmortizationResult:
    bond = security.bond
    price = trade.clean_price
    settlement = _start(trade)
    fraction = face / trade.face_amount
    cost = trade.transaction_cost * fraction
    opening = trade.opening
    pay = _pay_date_fn(inputs, security)
    if security.bond_type == "FIXED" and bond.coupon_freq == 0:
        basis = None
        if opening is not None:
            basis = RoundingPolicy.round_amount(opening.amortized_cost * fraction, security.currency)
        return zero_coupon_amortization(
            bond, face, settlement, price, cost, end, opening_cost=basis, pay_date=pay,
        )
    state = None
    if opening is not None:
        dirty = opening.amortized_cost + _accrued_at_settlement(inputs, security, trade, settlement)
        state = OpeningState(dirty=dirty * fraction, rate=opening.eir_periodic)
    if security.bond_type == "FIXED":
        return fixed_rate_amortization(bond, face, settlement, price, cost, end, opening=state, pay_date=pay)
    if security.bond_type == "FLOATING":
        return floating_amortization(
            bond, face, inputs.fixings, settlement, price, cost, end, opening=state, pay_date=pay,
        )
    if security.bond_type in ("MBS", "ABS"):
        scaled_bond = replace(bond, original_face=bond.original_face * fraction)
        projections = [
            _scaled(version, fraction, pay) for version in inputs.projections.get(security.security_id, [])
        ]
        return pass_through_amortization(
            scaled_bond, inputs.pool_factors.get(security.security_id, []), projections,
            settlement, face, price, cost, end,
        )
    return tips_amortization(bond, face, _cpi_series(inputs, security), settlement, price, cost, end, pay_date=pay)


def _pay_date_fn(inputs: Inputs, security: Security) -> Callable[[date], date]:
    if security.business_day_convention is None:
        return lambda day: day
    calendar = inputs.holidays[security.calendar_id]
    convention = security.business_day_convention
    return lambda day: adjust_payment_date(day, convention, calendar)


def _scaled(version: ProjectionVersion, fraction: Decimal, pay: Callable[[date], date]) -> ProjectionVersion:
    flows = tuple(
        CashFlow(
            pay(cash.pay_date),
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


def _accrued_at_settlement(
    inputs: Inputs, security: Security, trade: Trade, settlement: date | None = None
) -> Decimal:
    bond = security.bond
    settlement = settlement or trade.settlement_date
    if security.bond_type == "FIXED":
        return accrued_interest_on(bond, trade.face_amount, settlement)
    if security.bond_type == "FLOATING":
        rated = rated_periods(bond, inputs.fixings)
        return floating_accrued_on(bond, trade.face_amount, rated, settlement)
    if security.bond_type in ("MBS", "ABS"):
        return pass_through_accrued_on(bond, inputs.pool_factors.get(security.security_id, []), settlement)
    return tips_accrued_on(bond, trade.face_amount, _ref_cpi(inputs, security), settlement)


def _opening_warnings(inputs: Inputs, security: Security, trade: Trade) -> list[ValidationError]:
    opening = trade.opening
    computed = _accrued_at_settlement(inputs, security, trade, opening.as_of)
    if computed == opening.accrued_interest:
        return []
    return [ValidationError(
        "opening_balance.csv", None, "accrued_interest",
        f"{trade.lot_id}: opening accrued {opening.accrued_interest} differs from calculated {computed}",
    )]


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
