import csv
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from accrual.batch import run_batch
from accrual.io.parsing import ValidationFailed
from accrual.io.loaders import load_inputs

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
AS_OF = date(2024, 6, 30)
END = date(2024, 9, 30)
LOT = "L0001"


def _directory(target: Path, trades_lines: list[str], opening: str | None = None) -> Path:
    target.mkdir(parents=True)
    for source in SAMPLES.iterdir():
        if source.name != "trades.csv":
            shutil.copy(source, target / source.name)
    lines = (SAMPLES / "trades.csv").read_text(encoding="utf-8").splitlines()
    kept = [lines[0]] + [line for line in lines[1:] if line.split(",")[0] in trades_lines]
    (target / "trades.csv").write_text("\n".join(kept) + "\n", encoding="utf-8")
    if opening is not None:
        (target / "opening_balance.csv").write_text(opening, encoding="utf-8")
    return target


def _rows(path: Path, lot: str) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["date"]: row for row in csv.DictReader(handle) if row["lot_id"] == lot}


def test_carry_forward_reproduces_full_history(tmp_path: Path) -> None:
    trades = ["T0001", "T0008"]
    full_dir = _directory(tmp_path / "full", trades)
    full_out = tmp_path / "full.csv"
    run_batch(full_dir, full_out, END)
    full = _rows(full_out, LOT)
    at = full[AS_OF.isoformat()]

    opening = (
        "lot_id,as_of_date,face,amortized_cost,cumulative_amortization,accrued_interest,eir_periodic\n"
        f"{LOT},{AS_OF.isoformat()},700000,"
        f"{at['amortized_cost']},0.00,{at['accrued_interest_cum']},{at['eir']}\n"
    )
    carry_dir = _directory(tmp_path / "carry", ["T0001", "T0008"], opening)
    carry_out = tmp_path / "carry.csv"
    report = run_batch(carry_dir, carry_out, END)
    assert report.warnings == []
    carried = _rows(carry_out, LOT)

    later = [d for d in full if d > AS_OF.isoformat()]
    assert later and set(later) == set(carried)
    for day in later:
        for column in ("amortized_cost", "interest_income", "amortization", "accrued_interest_cum"):
            assert abs(Decimal(full[day][column]) - Decimal(carried[day][column])) <= Decimal("0.02"), (day, column)


def test_opening_must_match_a_buy_lot(tmp_path: Path) -> None:
    opening = "lot_id,as_of_date,face,amortized_cost,cumulative_amortization,accrued_interest,eir_periodic\nL9999,2024-06-30,1,1,0,0,0.02\n"
    directory = _directory(tmp_path / "bad", ["T0001"], opening)
    with pytest.raises(ValidationFailed) as excinfo:
        load_inputs(directory, END)
    assert any("no matching BUY" in str(error) for error in excinfo.value.errors)


def test_opening_face_cannot_exceed_purchased_face(tmp_path: Path) -> None:
    opening = "lot_id,as_of_date,face,amortized_cost,cumulative_amortization,accrued_interest,eir_periodic\nL0001,2024-06-30,2000000,1,0,0,0.02\n"
    directory = _directory(tmp_path / "big", ["T0001"], opening)
    with pytest.raises(ValidationFailed) as excinfo:
        load_inputs(directory, END)
    assert any("exceeds purchased face" in str(error) for error in excinfo.value.errors)
