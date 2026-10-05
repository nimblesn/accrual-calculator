from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


class Lot(Protocol):
    lot_id: str
    portfolio_id: str
    security_id: str
    settlement_date: date
    face_amount: Decimal


@dataclass(frozen=True)
class Sale:
    trade_id: str
    portfolio_id: str
    security_id: str
    settlement_date: date
    face: Decimal
    clean_price: Decimal
    transaction_cost: Decimal
    accrued_received: Decimal | None


@dataclass(frozen=True)
class Allocation:
    sale: Sale
    face: Decimal


def allocate_fifo(lots: list[Lot], sales: list[Sale]) -> tuple[dict[str, list[Allocation]], list[str]]:
    remaining = {lot.lot_id: lot.face_amount for lot in lots}
    allocations: dict[str, list[Allocation]] = {}
    shortfalls: list[str] = []
    for sale in sorted(sales, key=lambda s: (s.settlement_date, s.trade_id)):
        need = sale.face
        candidates = sorted(
            (
                lot for lot in lots
                if lot.portfolio_id == sale.portfolio_id
                and lot.security_id == sale.security_id
                and lot.settlement_date < sale.settlement_date
            ),
            key=lambda lot: (lot.settlement_date, lot.lot_id),
        )
        for lot in candidates:
            if need == 0:
                break
            taken = min(remaining[lot.lot_id], need)
            if taken > 0:
                allocations.setdefault(lot.lot_id, []).append(Allocation(sale, taken))
                remaining[lot.lot_id] -= taken
                need -= taken
        if need > 0:
            shortfalls.append(f"{sale.trade_id}: insufficient holdings, short by {need}")
    for lot_id, parts in allocations.items():
        dates = [part.sale.settlement_date for part in parts]
        if len(dates) != len(set(dates)):
            shortfalls.append(f"{lot_id}: more than one sale of the same lot on the same settlement date")
    return allocations, shortfalls
