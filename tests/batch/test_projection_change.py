import csv
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from accrual.__main__ import main
from accrual.batch import run_batch

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
CALC_END = date(2024, 6, 30)
CHANGE = "2024-04-01"


@pytest.fixture
def revised(tmp_path: Path) -> Path:
    """Samples plus SAMPLE0005 version 2 effective 2024-04-01 with 10% more interest on every flow."""
    directory = tmp_path / "in"
    shutil.copytree(SAMPLES, directory)
    path = directory / "projected_cashflows.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    extra = [
        {**row, "version": "2", "effective_date": CHANGE,
         "interest": str((Decimal(row["interest"]) * Decimal("1.1")).quantize(Decimal("0.01")))}
        for row in rows if row["security_id"] == "SAMPLE0005" and row["pay_date"] > CHANGE
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows + extra)
    return directory


def l0006(path: Path) -> dict[str, dict[str, str]]:
    return {row["date"]: row for row in csv.DictReader(path.open(encoding="utf-8")) if row["lot_id"] == "L0006"}


def test_prospective_default_keeps_book_and_changes_eir(revised: Path, tmp_path: Path) -> None:
    run_batch(SAMPLES, tmp_path / "base.csv", CALC_END)
    run_batch(revised, tmp_path / "prospective.csv", CALC_END)
    base, new = l0006(tmp_path / "base.csv"), l0006(tmp_path / "prospective.csv")
    assert new[CHANGE]["amortized_cost"] == base[CHANGE]["amortized_cost"]
    assert new["2024-03-31"]["eir"] == base["2024-03-31"]["eir"]
    assert Decimal(new[CHANGE]["eir"]) > Decimal(base[CHANGE]["eir"])  # richer flows, same book => higher EIR


def test_catch_up_revalues_book_at_old_eir(revised: Path, tmp_path: Path) -> None:
    run_batch(SAMPLES, tmp_path / "base.csv", CALC_END)
    run_batch(revised, tmp_path / "catch_up.csv", CALC_END, projection_change="CATCH_UP")
    base, new = l0006(tmp_path / "base.csv"), l0006(tmp_path / "catch_up.csv")
    assert Decimal(new[CHANGE]["amortized_cost"]) > Decimal(base[CHANGE]["amortized_cost"])
    assert new[CHANGE]["eir"] == base[CHANGE]["eir"]


def test_unknown_method_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_batch(SAMPLES, tmp_path / "out.csv", CALC_END, projection_change="RETROSPECTIVE")


def test_cli_option(revised: Path, tmp_path: Path) -> None:
    common = [str(revised), "--calc-end", CALC_END.isoformat()]
    assert main([*common, "--output", str(tmp_path / "default.csv")]) == 0
    assert main([*common, "--output", str(tmp_path / "prospective.csv"), "--projection-change", "PROSPECTIVE"]) == 0
    assert main([*common, "--output", str(tmp_path / "catch_up.csv"), "--projection-change", "CATCH_UP"]) == 0
    assert l0006(tmp_path / "default.csv") == l0006(tmp_path / "prospective.csv")
    assert l0006(tmp_path / "catch_up.csv") != l0006(tmp_path / "prospective.csv")
