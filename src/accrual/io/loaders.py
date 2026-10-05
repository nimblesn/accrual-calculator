from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from accrual.accrual.floating import Fixing, rated_periods
from accrual.accrual.pass_through import PoolFactor, factor_on, period_balances
from accrual.daycount.base import UnsupportedDayCountError
from accrual.daycount.types import get_day_count
from accrual.disposal import Allocation, Sale, allocate_fifo
from accrual.io.parsing import RowReader, Table, ValidationError, ValidationFailed
from accrual.models.bond import FixedRateBond, FloatingRateBond, PassThroughBond, TipsBond
from accrual.models.period import CashFlow, ProjectionVersion

BOND_TYPES = ("FIXED", "FLOATING", "MBS", "ABS", "TIPS")
BUSINESS_DAY_CONVENTIONS = ("FOLLOWING", "MODIFIED_FOLLOWING", "PRECEDING")
SECURITY_MASTER = "security_master.csv"
TRADES = "trades.csv"
FLOATING_INDEX = "floating_rate_index.csv"
CPI_INDEX = "cpi_index.csv"
POOL_FACTOR = "pool_factor.csv"
PROJECTED = "projected_cashflows.csv"
DAYCOUNT_CODE = "daycount_code.csv"
OPENING_BALANCE = "opening_balance.csv"
HOLIDAY_CALENDAR = "holiday_calendar.csv"

_MASTER_COLUMNS = (
    "security_id", "bond_type", "currency", "issue_date", "dated_date", "maturity_date",
    "first_coupon_date", "coupon_rate_pct", "coupon_freq", "day_count_code", "eom_flag",
    "redemption_price_pct", "index_name", "spread_pct", "multiplier", "cap_pct", "floor_pct",
    "original_face", "pool_id", "payment_delay_days", "cpi_index_name", "base_ref_cpi",
    "deflation_floor_flag",
)
_TRADE_COLUMNS = (
    "trade_id", "lot_id", "security_id", "side", "trade_date", "settlement_date", "face_amount",
    "clean_price", "accrued_interest_paid", "transaction_cost",
)
_FIXING_COLUMNS = ("index_name", "reset_date", "rate_pct")
_CPI_COLUMNS = ("cpi_index_name", "month", "cpi_value")
_POOL_COLUMNS = ("security_id", "effective_date", "factor")
_PROJECTED_COLUMNS = ("security_id", "version", "effective_date", "pay_date", "principal", "interest")
_DAYCOUNT_COLUMNS = ("code_no", "code_name")
_OPENING_COLUMNS = ("lot_id", "as_of_date", "face", "amortized_cost", "cumulative_amortization", "accrued_interest", "eir_periodic")
_HOLIDAY_COLUMNS = ("calendar_id", "date")


@dataclass(frozen=True)
class Security:
    security_id: str
    bond_type: str
    currency: str
    bond: FixedRateBond | FloatingRateBond | PassThroughBond | TipsBond
    cpi_index_name: str | None
    business_day_convention: str | None = None
    calendar_id: str | None = None


@dataclass(frozen=True)
class OpeningBalance:
    lot_id: str
    as_of: date
    face: Decimal
    amortized_cost: Decimal
    accrued_interest: Decimal
    eir_periodic: Decimal | None


@dataclass(frozen=True)
class Trade:
    trade_id: str
    lot_id: str
    portfolio_id: str
    security_id: str
    trade_date: date
    settlement_date: date
    face_amount: Decimal
    clean_price: Decimal
    accrued_interest_paid: Decimal | None
    transaction_cost: Decimal
    opening: OpeningBalance | None = None


@dataclass(frozen=True)
class Inputs:
    calc_end: date
    securities: dict[str, Security]
    trades: list[Trade]
    fixings: list[Fixing]
    cpi: dict[str, dict[tuple[int, int], Decimal]]
    pool_factors: dict[str, list[PoolFactor]]
    projections: dict[str, list[ProjectionVersion]]
    sales: list[Sale] = field(default_factory=list)
    allocations: dict[str, list[Allocation]] = field(default_factory=dict)
    opening_as_of: date | None = None
    holidays: dict[str, frozenset[date]] = field(default_factory=dict)
    warnings: list[ValidationError] = field(default_factory=list)


def load_inputs(directory: Path, calc_end: date) -> Inputs:
    errors: list[ValidationError] = []
    securities = _load_securities(Table(directory, SECURITY_MASTER, _MASTER_COLUMNS, errors), errors)
    fixings = _load_fixings(Table(directory, FLOATING_INDEX, _FIXING_COLUMNS, errors), errors)
    cpi = _load_cpi(Table(directory, CPI_INDEX, _CPI_COLUMNS, errors), errors)
    pool_factors = _load_pool_factors(Table(directory, POOL_FACTOR, _POOL_COLUMNS, errors), securities, errors)
    projections = _load_projections(Table(directory, PROJECTED, _PROJECTED_COLUMNS, errors), securities, errors)
    Table(directory, DAYCOUNT_CODE, _DAYCOUNT_COLUMNS, errors)
    trades, sales = _load_trades(Table(directory, TRADES, _TRADE_COLUMNS, errors), securities, calc_end, errors)
    openings, as_of = _load_openings(_optional(directory, OPENING_BALANCE, _OPENING_COLUMNS, errors), errors)
    holidays = _load_holidays(_optional(directory, HOLIDAY_CALENDAR, _HOLIDAY_COLUMNS, errors), errors)
    for security in securities.values():
        if security.calendar_id is not None and security.calendar_id not in holidays:
            errors.append(ValidationError(
                SECURITY_MASTER, None, "calendar_id",
                f"{security.security_id}: calendar {security.calendar_id!r} is not in {HOLIDAY_CALENDAR}",
            ))
    trades, sales = _apply_openings(trades, sales, openings, as_of, securities, errors)
    allocations, shortfalls = allocate_fifo(trades, sales)
    errors.extend(ValidationError(TRADES, None, "face_amount", message) for message in shortfalls)

    inputs = Inputs(
        calc_end=calc_end,
        securities=securities,
        trades=trades,
        fixings=fixings,
        cpi=cpi,
        pool_factors=pool_factors,
        projections=projections,
        sales=sales,
        allocations=allocations,
        opening_as_of=as_of,
        holidays=holidays,
    )
    errors.extend(_coverage_errors(inputs))
    if errors:
        raise ValidationFailed(errors)
    return inputs


def _load_securities(table: Table, errors: list[ValidationError]) -> dict[str, Security]:
    securities: dict[str, Security] = {}
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        security_id = reader.text("security_id")
        bond_type = reader.enum("bond_type", BOND_TYPES)
        currency = reader.currency("currency")
        issue = reader.date("issue_date")
        dated = reader.date("dated_date")
        maturity = reader.date("maturity_date")
        first_coupon = reader.date("first_coupon_date", required=False)
        rate = reader.decimal("coupon_rate_pct", percent=True)
        freq = reader.integer("coupon_freq")
        day_count = reader.text("day_count_code")
        eom = reader.yes_no("eom_flag")
        redemption = reader.decimal("redemption_price_pct")
        convention = reader.enum("business_day_conv", BUSINESS_DAY_CONVENTIONS, required=False)
        calendar_id = reader.text("calendar_id", required=False)
        if convention is not None and calendar_id is None:
            reader.fail("calendar_id", "a business day convention needs a calendar_id")
        if day_count is not None:
            try:
                get_day_count(day_count)
            except UnsupportedDayCountError as exc:
                reader.fail("day_count_code", str(exc))
        if security_id is not None and security_id in securities:
            reader.fail("security_id", "duplicate security_id")
            continue
        if not reader.ok or None in (
            security_id, bond_type, currency, issue, dated, maturity, rate, freq, day_count, eom, redemption
        ):
            continue
        bond = _build_bond(
            reader, table.name, line, bond_type, security_id, currency, issue, dated, maturity,
            first_coupon, rate, freq, day_count, eom, redemption, errors,
        )
        if bond is not None:
            securities[security_id] = Security(
                security_id, bond_type, currency, bond, values.get("cpi_index_name") or None,
                convention, calendar_id,
            )
    return securities


def _build_bond(
    reader, file, line, bond_type, security_id, currency, issue, dated, maturity,
    first_coupon, rate, freq, day_count, eom, redemption, errors,
):
    try:
        if bond_type == "FIXED":
            return FixedRateBond(
                security_id=security_id, currency=currency, issue_date=issue, dated_date=dated,
                maturity_date=maturity, first_coupon_date=first_coupon, coupon_rate=rate,
                coupon_freq=freq, day_count_code=day_count, end_of_month=eom,
                redemption_price=redemption,
            )
        if bond_type == "FLOATING":
            index_name = reader.text("index_name")
            spread = reader.decimal("spread_pct", required=False, percent=True) or Decimal(0)
            multiplier = reader.decimal("multiplier", required=False) or Decimal(1)
            cap = reader.decimal("cap_pct", required=False, percent=True)
            floor = reader.decimal("floor_pct", required=False, percent=True)
            if not reader.ok or index_name is None:
                return None
            return FloatingRateBond(
                security_id=security_id, currency=currency, issue_date=issue, dated_date=dated,
                maturity_date=maturity, first_coupon_date=first_coupon, coupon_freq=freq,
                day_count_code=day_count, end_of_month=eom, redemption_price=redemption,
                index_name=index_name, spread=spread, multiplier=multiplier, cap=cap, floor=floor,
            )
        if bond_type in ("MBS", "ABS"):
            original = reader.decimal("original_face")
            delay = reader.integer("payment_delay_days", required=False) or 0
            if not reader.ok or original is None:
                return None
            return PassThroughBond(
                security_id=security_id, bond_type=bond_type, currency=currency, issue_date=issue,
                dated_date=dated, maturity_date=maturity, coupon_rate=rate, coupon_freq=freq,
                day_count_code=day_count, end_of_month=eom, original_face=original,
                payment_delay_days=delay,
            )
        base = reader.decimal("base_ref_cpi")
        floor_flag = reader.yes_no("deflation_floor_flag")
        if not reader.ok or base is None or floor_flag is None:
            return None
        return TipsBond(
            security_id=security_id, currency=currency, issue_date=issue, dated_date=dated,
            maturity_date=maturity, first_coupon_date=first_coupon, real_coupon_rate=rate,
            coupon_freq=freq, day_count_code=day_count, end_of_month=eom, base_ref_cpi=base,
            deflation_floor=floor_flag,
        )
    except ValueError as exc:
        errors.append(ValidationError(file, line, None, f"{security_id}: {exc}"))
        return None


def _load_fixings(table: Table, errors: list[ValidationError]) -> list[Fixing]:
    fixings: list[Fixing] = []
    seen: set[tuple[str, date]] = set()
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        index_name = reader.text("index_name")
        reset = reader.date("reset_date")
        rate = reader.decimal("rate_pct", percent=True)
        if not reader.ok or index_name is None or reset is None or rate is None:
            continue
        if (index_name, reset) in seen:
            reader.fail("reset_date", "duplicate fixing for index and reset date")
            continue
        seen.add((index_name, reset))
        fixings.append(Fixing(index_name, reset, rate))
    return fixings


def _load_cpi(table: Table, errors: list[ValidationError]) -> dict[str, dict[tuple[int, int], Decimal]]:
    cpi: dict[str, dict[tuple[int, int], Decimal]] = {}
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        name = reader.text("cpi_index_name")
        month = reader.month("month")
        value = reader.decimal("cpi_value")
        if not reader.ok or name is None or month is None or value is None:
            continue
        series = cpi.setdefault(name, {})
        if month in series:
            reader.fail("month", "duplicate CPI month")
            continue
        series[month] = value
    return cpi


def _load_pool_factors(
    table: Table, securities: dict[str, Security], errors: list[ValidationError]
) -> dict[str, list[PoolFactor]]:
    factors: dict[str, list[PoolFactor]] = {}
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        security_id = reader.text("security_id")
        effective = reader.date("effective_date")
        factor = reader.decimal("factor")
        if not reader.ok or security_id is None or effective is None or factor is None:
            continue
        security = securities.get(security_id)
        if security is None or security.bond_type not in ("MBS", "ABS"):
            reader.fail("security_id", "pool factor must reference an MBS or ABS security")
            continue
        factors.setdefault(security_id, []).append(PoolFactor(effective, factor))
    return factors


def _load_projections(
    table: Table, securities: dict[str, Security], errors: list[ValidationError]
) -> dict[str, list[ProjectionVersion]]:
    grouped: dict[str, dict[int, tuple[date, list[CashFlow]]]] = {}
    bases: dict[tuple[str, int], Decimal | None] = {}
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        security_id = reader.text("security_id")
        version = reader.integer("version")
        effective = reader.date("effective_date")
        pay = reader.date("pay_date")
        security = securities.get(security_id) if security_id else None
        currency = security.currency if security else "USD"
        principal = reader.amount("principal", currency)
        interest = reader.amount("interest", currency)
        basis = reader.amount("basis_face", currency, required=False)
        if basis is not None and basis <= 0:
            reader.fail("basis_face", "must be positive")
        if not reader.ok or None in (security_id, version, effective, pay, principal, interest):
            continue
        if security is None or security.bond_type not in ("MBS", "ABS"):
            reader.fail("security_id", "projected cash flows must reference an MBS or ABS security")
            continue
        versions = grouped.setdefault(security_id, {})
        existing = versions.get(version)
        if existing is not None and existing[0] != effective:
            reader.fail("effective_date", "version has inconsistent effective dates")
            continue
        if bases.setdefault((security_id, version), basis) != basis:
            reader.fail("basis_face", "version has inconsistent basis_face")
            continue
        versions.setdefault(version, (effective, []))[1].append(CashFlow(pay, principal, interest))
    return {
        security_id: [
            ProjectionVersion(
                version=version, effective_date=effective, flows=tuple(flows),
                basis_face=bases.get((security_id, version)),
            )
            for version, (effective, flows) in sorted(versions.items())
        ]
        for security_id, versions in grouped.items()
    }


def _load_trades(
    table: Table, securities: dict[str, Security], calc_end: date, errors: list[ValidationError]
) -> tuple[list[Trade], list[Sale]]:
    trades: list[Trade] = []
    sales: list[Sale] = []
    seen_ids: set[str] = set()
    seen_lots: set[str] = set()
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        trade_id = reader.text("trade_id")
        lot_id = reader.text("lot_id", required=False)
        portfolio_id = reader.text("portfolio_id")
        security_id = reader.text("security_id")
        side = reader.enum("side", ("BUY", "SELL"))
        trade_date = reader.date("trade_date")
        settlement = reader.date("settlement_date")
        security = securities.get(security_id) if security_id else None
        if security_id is not None and security is None:
            reader.fail("security_id", f"unknown security_id {security_id!r}")
        currency = security.currency if security else "USD"
        face = reader.amount("face_amount", currency)
        price = reader.decimal("clean_price")
        accrued = reader.amount("accrued_interest_paid", currency, required=side == "BUY")
        cost = reader.amount("transaction_cost", currency)
        if side == "BUY" and lot_id is None:
            reader.fail("lot_id", "BUY lots need a lot_id")
        if side == "SELL" and lot_id is not None:
            reader.fail("lot_id", "SELL lots are chosen FIFO; leave lot_id empty")
        if trade_id is not None:
            if trade_id in seen_ids:
                reader.fail("trade_id", "duplicate trade_id")
            seen_ids.add(trade_id)
        if side == "BUY" and lot_id is not None:
            if lot_id in seen_lots:
                reader.fail("lot_id", "duplicate lot_id")
            seen_lots.add(lot_id)
        if trade_date is not None and settlement is not None and trade_date > settlement:
            reader.fail("settlement_date", "settlement date is before trade date")
        if security is not None and settlement is not None:
            upper_ok = settlement <= calc_end if side == "SELL" else settlement < calc_end
            if not (security.bond.dated_date <= settlement and upper_ok):
                reader.fail("settlement_date", "settlement is outside the bond's life or the calc window")
        if not reader.ok or None in (trade_id, portfolio_id, security_id, trade_date, settlement, face, price, cost):
            continue
        if side == "SELL":
            sales.append(Sale(
                trade_id=trade_id, portfolio_id=portfolio_id, security_id=security_id,
                settlement_date=settlement, face=face, clean_price=price, transaction_cost=cost,
                accrued_received=accrued,
            ))
            continue
        trades.append(
            Trade(
                trade_id=trade_id, lot_id=lot_id, portfolio_id=portfolio_id, security_id=security_id,
                trade_date=trade_date, settlement_date=settlement, face_amount=face, clean_price=price,
                accrued_interest_paid=accrued, transaction_cost=cost,
            )
        )
    return trades, sales


def _optional(directory: Path, name: str, required: tuple[str, ...], errors: list[ValidationError]) -> Table | None:
    if not (directory / name).exists():
        return None
    return Table(directory, name, required, errors)


def _load_openings(
    table: Table | None, errors: list[ValidationError]
) -> tuple[dict[str, OpeningBalance], date | None]:
    openings: dict[str, OpeningBalance] = {}
    as_of: date | None = None
    if table is None:
        return openings, as_of
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        lot_id = reader.text("lot_id")
        row_as_of = reader.date("as_of_date")
        face = reader.decimal("face")
        amortized = reader.decimal("amortized_cost")
        accrued = reader.decimal("accrued_interest")
        reader.decimal("cumulative_amortization", required=False)
        eir = reader.decimal("eir_periodic", required=False)
        if not reader.ok or None in (lot_id, row_as_of, face, amortized, accrued):
            continue
        if as_of is None:
            as_of = row_as_of
        elif row_as_of != as_of:
            reader.fail("as_of_date", "all opening balances must share one as_of_date")
            continue
        if lot_id in openings:
            reader.fail("lot_id", "duplicate opening balance for lot")
            continue
        openings[lot_id] = OpeningBalance(lot_id, row_as_of, face, amortized, accrued, eir)
    return openings, as_of


def _apply_openings(
    trades: list[Trade],
    sales: list[Sale],
    openings: dict[str, OpeningBalance],
    as_of: date | None,
    securities: dict[str, Security],
    errors: list[ValidationError],
) -> tuple[list[Trade], list[Sale]]:
    if as_of is None:
        return trades, sales
    kept: list[Trade] = []
    buy_lots = {trade.lot_id for trade in trades}
    for lot_id in openings:
        if lot_id not in buy_lots:
            errors.append(ValidationError(OPENING_BALANCE, None, "lot_id", f"{lot_id}: no matching BUY in trades"))
    for trade in trades:
        opening = openings.get(trade.lot_id)
        if trade.settlement_date > as_of:
            if opening is not None:
                errors.append(ValidationError(OPENING_BALANCE, None, "lot_id",
                                              f"{trade.lot_id}: opening balance predates its purchase"))
            kept.append(trade)
            continue
        if opening is None:
            continue
        security = securities[trade.security_id]
        if security.bond_type not in ("FIXED", "FLOATING"):
            errors.append(ValidationError(OPENING_BALANCE, None, "lot_id",
                                          f"{trade.lot_id}: opening balances are supported for FIXED and FLOATING"))
            continue
        if security.bond.coupon_freq != 0 and opening.eir_periodic is None:
            errors.append(ValidationError(OPENING_BALANCE, None, "eir_periodic",
                                          f"{trade.lot_id}: eir_periodic is required"))
            continue
        if opening.face > trade.face_amount:
            errors.append(ValidationError(OPENING_BALANCE, None, "face",
                                          f"{trade.lot_id}: opening face exceeds purchased face"))
            continue
        kept.append(replace(
            trade, face_amount=opening.face, accrued_interest_paid=None,
            transaction_cost=Decimal(0), opening=opening,
        ))
    kept_sales = [sale for sale in sales if sale.settlement_date > as_of]
    return kept, kept_sales


def _load_holidays(table: Table | None, errors: list[ValidationError]) -> dict[str, frozenset[date]]:
    calendars: dict[str, set[date]] = {}
    if table is None:
        return {}
    for line, values in table.rows:
        reader = RowReader(table.name, line, values, errors)
        calendar_id = reader.text("calendar_id")
        day = reader.date("date")
        if not reader.ok or calendar_id is None or day is None:
            continue
        days = calendars.setdefault(calendar_id, set())
        if day in days:
            reader.fail("date", "duplicate holiday")
            continue
        days.add(day)
    return {name: frozenset(days) for name, days in calendars.items()}


def _coverage_errors(inputs: Inputs) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for trade in inputs.trades:
        security = inputs.securities[trade.security_id]
        if inputs.calc_end > security.bond.maturity_date:
            errors.append(ValidationError(TRADES, None, "lot_id", f"{trade.lot_id}: calc_end is after maturity"))
            continue
        try:
            if security.bond_type == "FLOATING":
                rated_periods(security.bond, inputs.fixings)
            if security.bond_type in ("MBS", "ABS"):
                period_balances(security.bond, inputs.pool_factors.get(security.security_id, []))
                _require_projection(inputs, security, trade, errors)
            if security.bond_type == "TIPS":
                _require_cpi(inputs, security, trade, errors)
        except ValueError as exc:
            errors.append(ValidationError(TRADES, None, "lot_id", f"{trade.lot_id}: {exc}"))
    return errors


def _require_projection(inputs: Inputs, security: Security, trade: Trade, errors: list[ValidationError]) -> None:
    versions = inputs.projections.get(security.security_id, [])
    if not any(v.effective_date <= trade.settlement_date for v in versions):
        errors.append(ValidationError(
            PROJECTED, None, "effective_date",
            f"{trade.lot_id}: no projection effective on or before settlement",
        ))
        return
    factors = inputs.pool_factors.get(security.security_id, [])
    for day in {v.effective_date for v in versions if v.basis_face is not None} | {trade.settlement_date}:
        if any(v.basis_face is not None for v in versions) and factor_on(factors, day) is None:
            errors.append(ValidationError(
                POOL_FACTOR, None, "effective_date",
                f"{trade.lot_id}: no pool factor on or before {day} to restate the lot to basis_face",
            ))
            return
    last_pay = max(cash.pay_date for v in versions for cash in v.flows)
    if last_pay < security.bond.maturity_date:
        errors.append(ValidationError(
            PROJECTED, None, "pay_date", f"{trade.lot_id}: projected cash flows end before maturity",
        ))


def _require_cpi(inputs: Inputs, security: Security, trade: Trade, errors: list[ValidationError]) -> None:
    if security.cpi_index_name is None:
        errors.append(ValidationError(SECURITY_MASTER, None, "cpi_index_name", f"{security.security_id}: missing"))
        return
    series = inputs.cpi.get(security.cpi_index_name, {})
    maturity = security.bond.maturity_date
    first = trade.settlement_date.year * 12 + trade.settlement_date.month - 1 - 3
    last = maturity.year * 12 + maturity.month - 1 - 2
    missing = [
        f"{total // 12:04d}-{total % 12 + 1:02d}"
        for total in range(first, last + 1)
        if (total // 12, total % 12 + 1) not in series
    ]
    if missing:
        errors.append(ValidationError(
            CPI_INDEX, None, "month", f"{security.cpi_index_name}: missing CPI months through maturity: {', '.join(missing)}",
        ))
