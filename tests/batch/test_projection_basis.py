import csv
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from accrual.batch import run_batch
from accrual.io.parsing import ValidationFailed

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
CALC_END = date(2024, 6, 30)
PROJECTED = "projected_cashflows.csv"
# SAMPLE0005 projection is effective 2024-01-01 (factor 1.0); lot L0006 is 48,750,000 at factor 0.975,
# i.e. 50,000,000 at the effective date, so basis_face 50,000,000 leaves the lot's share at exactly 1.
BASIS = "50000000.00"


@pytest.fixture
def inputs(tmp_path: Path) -> Path:
    directory = tmp_path / "in"
    shutil.copytree(SAMPLES, directory)
    return directory


def with_basis(directory: Path, basis_for: dict[str, str]) -> None:
    path = directory / PROJECTED
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, [*rows[0].keys(), "basis_face"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "basis_face": basis_for.get(row["security_id"], "")})


def split_lot(directory: Path) -> None:
    """Replace lot L0006 (SAMPLE0005, 48,750,000) with 60% / 40% lots at the same price and date."""
    path = directory / "trades.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    original = next(line for line in lines if line.startswith("T0006,"))
    assert original == "T0006,L0006,P03,SAMPLE0005,BUY,2024-03-20,2024-03-20,48750000,100.250,141510.42,0"
    lines.remove(original)
    lines += [
        "T0006A,L0006A,P03,SAMPLE0005,BUY,2024-03-20,2024-03-20,29250000,100.250,84906.25,0",
        "T0006B,L0006B,P04,SAMPLE0005,BUY,2024-03-20,2024-03-20,19500000,100.250,56604.17,0",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def lot_rows(out: Path, prefix: str) -> list[dict[str, str]]:
    return [row for row in csv.DictReader(out.open(encoding="utf-8")) if row["lot_id"].startswith(prefix)]


def test_unit_ratio_basis_matches_lot_face_projection(inputs: Path, tmp_path: Path) -> None:
    run_batch(SAMPLES, tmp_path / "base.csv", CALC_END)
    with_basis(inputs, {"SAMPLE0005": BASIS})
    run_batch(inputs, tmp_path / "basis.csv", CALC_END)
    assert lot_rows(tmp_path / "basis.csv", "L0006") == lot_rows(tmp_path / "base.csv", "L0006")


def test_split_lots_share_one_projection(inputs: Path, tmp_path: Path) -> None:
    run_batch(SAMPLES, tmp_path / "base.csv", CALC_END)
    with_basis(inputs, {"SAMPLE0005": BASIS})
    split_lot(inputs)
    run_batch(inputs, tmp_path / "split.csv", CALC_END)

    base = lot_rows(tmp_path / "base.csv", "L0006")
    a = lot_rows(tmp_path / "split.csv", "L0006A")
    b = lot_rows(tmp_path / "split.csv", "L0006B")
    assert len(a) == len(b) == len(base)
    for whole, part_a, part_b in zip(base, a, b):
        # Same cash flows per unit of face => same EIR, except that each lot's acquisition cost
        # (accrued interest at settlement) is rounded to the cent separately: last-digit differences only.
        for part in (part_a, part_b):
            assert abs(Decimal(part["eir"]) - Decimal(whole["eir"])) <= Decimal("1E-11")
        total = Decimal(part_a["amortized_cost"]) + Decimal(part_b["amortized_cost"])
        assert abs(total - Decimal(whole["amortized_cost"])) <= Decimal("0.01")


def test_without_basis_split_lots_overstate_flows(inputs: Path, tmp_path: Path) -> None:
    # The pre-basis_face behaviour this change fixes: each lot takes the whole projection as its own.
    run_batch(SAMPLES, tmp_path / "base.csv", CALC_END)
    split_lot(inputs)
    run_batch(inputs, tmp_path / "split.csv", CALC_END)
    assert lot_rows(tmp_path / "split.csv", "L0006A")[0]["eir"] != lot_rows(tmp_path / "base.csv", "L0006")[0]["eir"]


def test_inconsistent_basis_within_version_rejected(inputs: Path, tmp_path: Path) -> None:
    with_basis(inputs, {"SAMPLE0005": BASIS})
    path = inputs / PROJECTED
    lines = path.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("SAMPLE0005,") and i > 1 and lines[i - 1].startswith("SAMPLE0005,"))
    lines[index] = lines[index].removesuffix(BASIS) + "49000000.00"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValidationFailed) as failure:
        run_batch(inputs, tmp_path / "out.csv", CALC_END)
    assert any(error.field == "basis_face" for error in failure.value.errors)
