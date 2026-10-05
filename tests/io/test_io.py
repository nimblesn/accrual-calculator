import csv
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from accrual.batch import run_batch
from accrual.io.loaders import load_inputs
from accrual.io.parsing import RowReader, ValidationError, ValidationFailed

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
CALC_END = date(2024, 6, 30)


def reader_for(values: dict[str, str]) -> tuple[RowReader, list[ValidationError]]:
    errors: list[ValidationError] = []
    return RowReader("test.csv", 2, values, errors), errors


@pytest.mark.parametrize("value", ["1E-5", "1,000", "abc", "1.2.3"])
def test_decimal_rejects_exponents_separators_and_garbage(value: str) -> None:
    reader, errors = reader_for({"x": value})
    assert reader.decimal("x") is None
    assert len(errors) == 1 and errors[0].row == 2 and errors[0].field == "x"


def test_percent_field_is_converted_to_fraction() -> None:
    reader, _ = reader_for({"rate": "4.250"})
    assert reader.decimal("rate", percent=True) == Decimal("0.0425")


def test_date_must_be_iso() -> None:
    reader, errors = reader_for({"d": "2024/02/22"})
    assert reader.date("d") is None
    assert errors and "YYYY-MM-DD" in errors[0].message


def test_enum_and_yes_no_are_strict() -> None:
    reader, errors = reader_for({"side": "buy", "flag": "y"})
    assert reader.enum("side", ("BUY", "SELL")) is None
    assert reader.yes_no("flag") is None
    assert len(errors) == 2


def test_jpy_amount_cannot_have_decimals() -> None:
    reader, errors = reader_for({"amt": "1000.5"})
    assert reader.amount("amt", "JPY") is None
    assert "JPY" in errors[0].message


def test_empty_required_value_is_reported() -> None:
    reader, errors = reader_for({"x": ""})
    assert reader.text("x") is None
    assert errors[0].message == "required value is empty"


def test_sample_directory_fails_validation_with_row_numbers() -> None:
    with pytest.raises(ValidationFailed) as excinfo:
        load_inputs(SAMPLES, CALC_END)
    messages = [str(error) for error in excinfo.value.errors]
    assert any("trades.csv:9" in message and "SELL" in message for message in messages)
    assert any("projected cash flows end before calc_end" in message for message in messages)


def _subset_directory(target: Path) -> Path:
    target.mkdir(parents=True)
    for source in SAMPLES.iterdir():
        if source.name != "trades.csv":
            shutil.copy(source, target / source.name)
    lines = (SAMPLES / "trades.csv").read_text(encoding="utf-8").splitlines()
    keep = [lines[0]] + [line for line in lines[1:] if line.split(",")[0] in ("T0001", "T0003", "T0005")]
    (target / "trades.csv").write_text("\n".join(keep) + "\n", encoding="utf-8")
    return target


def test_batch_runs_for_valid_subset_and_writes_schema(tmp_path: Path) -> None:
    directory = _subset_directory(tmp_path / "in")
    output = tmp_path / "out.csv"
    report = run_batch(directory, output, CALC_END)

    assert report.lots == 3
    assert report.warnings == []
    assert report.rows == (CALC_END - date(2024, 2, 22)).days + (CALC_END - date(2024, 3, 4)).days + (
        CALC_END - date(2024, 4, 12)
    ).days

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0].keys()) == [
        "lot_id", "security_id", "currency", "date", "accrued_interest_cum", "accrued_interest_daily",
        "interest_income", "amortization", "amortized_cost", "eir", "inflation_accrual",
    ]
    jpy = [row for row in rows if row["lot_id"] == "L0003"]
    assert all("." not in row["amortized_cost"] for row in jpy)
    assert all(row["eir"] == "" for row in jpy)


def test_accrued_paid_mismatch_is_reported_as_warning(tmp_path: Path) -> None:
    directory = _subset_directory(tmp_path / "in")
    trades = directory / "trades.csv"
    trades.write_text(trades.read_text(encoding="utf-8").replace("4368.06", "5312.50"), encoding="utf-8")
    report = run_batch(directory, tmp_path / "out.csv", CALC_END)
    assert len(report.warnings) == 1
    assert "L0001" in report.warnings[0].message
