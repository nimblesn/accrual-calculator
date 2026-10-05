import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from accrual.batch import run_batch
from accrual.disposal import Sale, allocate_fifo

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class Lot:
    def __init__(self, lot_id, settlement, face):
        self.lot_id = lot_id
        self.portfolio_id = "P01"
        self.security_id = "S1"
        self.settlement_date = settlement
        self.face_amount = face


def sale(trade_id, settlement, face, portfolio="P01", security="S1"):
    return Sale(trade_id, portfolio, security, settlement, face, Decimal("100"), Decimal("0"), None)


def test_fifo_takes_oldest_lot_first() -> None:
    lots = [Lot("L2", date(2024, 3, 1), Decimal("500")), Lot("L1", date(2024, 2, 1), Decimal("1000"))]
    allocations, errors = allocate_fifo(lots, [sale("S", date(2024, 5, 1), Decimal("1200"))])
    assert errors == []
    assert [(lot, a.face) for lot, parts in allocations.items() for a in parts] == [
        ("L1", Decimal("1000")),
        ("L2", Decimal("200")),
    ]


def test_sale_only_considers_lots_bought_before_it_settles() -> None:
    lots = [Lot("L1", date(2024, 6, 1), Decimal("1000"))]
    allocations, errors = allocate_fifo(lots, [sale("S", date(2024, 5, 1), Decimal("100"))])
    assert allocations == {}
    assert errors and "insufficient holdings" in errors[0]


def test_other_portfolio_or_security_is_not_sold() -> None:
    lots = [Lot("L1", date(2024, 1, 1), Decimal("1000"))]
    _, errors = allocate_fifo(lots, [sale("S", date(2024, 5, 1), Decimal("100"), portfolio="P09")])
    assert errors


def test_two_sales_of_one_lot_on_one_day_are_rejected() -> None:
    lots = [Lot("L1", date(2024, 1, 1), Decimal("1000"))]
    sales = [sale("S1", date(2024, 5, 1), Decimal("100")), sale("S2", date(2024, 5, 1), Decimal("100"))]
    _, errors = allocate_fifo(lots, sales)
    assert any("same settlement date" in error for error in errors)


def test_partial_sale_derecognizes_pro_rata_and_books_gain() -> None:
    out = Path(__file__).resolve().parents[2] / "output" / "test_disposal.csv"
    out.parent.mkdir(exist_ok=True)
    run_batch(SAMPLES, out, date(2024, 6, 30))
    rows = [r for r in csv.DictReader(out.open(encoding="utf-8", newline="")) if r["lot_id"] == "L0001"]
    sale_row = next(r for r in rows if r["date"] == "2024-05-22")
    before = Decimal(sale_row["amortized_cost"])
    assert sale_row["disposal_face"] == "300000.00"
    assert sale_row["disposal_clean_proceeds"] == "301500.00"
    assert sale_row["derecognized_amortized_cost"] == format(
        (Decimal(sale_row["amortized_cost"]) * Decimal("0.3")).quantize(Decimal("0.01")), "f"
    )
    assert sale_row["realized_gain_loss"] == format(
        Decimal(sale_row["disposal_clean_proceeds"]) - Decimal(sale_row["derecognized_amortized_cost"]), "f"
    )
    next_day = next(r for r in rows if r["date"] == "2024-05-23")
    assert abs(
        Decimal(next_day["amortized_cost"])
        - (before - Decimal(sale_row["derecognized_amortized_cost"]) + Decimal(next_day["amortization"]))
    ) <= Decimal("0.01")
