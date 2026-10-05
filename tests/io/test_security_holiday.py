import csv
import shutil
from datetime import date
from pathlib import Path

import pytest

from accrual.io.loaders import load_inputs
from accrual.io.parsing import ValidationFailed

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _master_with(tmp_path: Path, security_1: dict[str, str]) -> Path:
    for source in SAMPLES.iterdir():
        shutil.copy(source, tmp_path / source.name)
    path = tmp_path / "security_master.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    fieldnames = list(rows[0].keys())
    for row in rows:
        if row["security_id"] == "SAMPLE0001":
            row.update(security_1)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return tmp_path


def test_holiday_rule_is_read_into_the_security(tmp_path: Path) -> None:
    directory = _master_with(tmp_path, {"business_day_conv": "FOLLOWING", "calendar_id": "US"})
    inputs = load_inputs(directory, date(2024, 6, 30))
    security = inputs.securities["SAMPLE0001"]
    assert security.business_day_convention == "FOLLOWING"
    assert security.calendar_id == "US"
    assert inputs.securities["SAMPLE0002"].business_day_convention is None


def test_unknown_convention_is_rejected(tmp_path: Path) -> None:
    directory = _master_with(tmp_path, {"business_day_conv": "NEXT_DAY", "calendar_id": "US"})
    with pytest.raises(ValidationFailed) as excinfo:
        load_inputs(directory, date(2024, 6, 30))
    assert any("business_day_conv" in str(error) for error in excinfo.value.errors)


def test_convention_without_calendar_is_rejected(tmp_path: Path) -> None:
    directory = _master_with(tmp_path, {"business_day_conv": "FOLLOWING", "calendar_id": ""})
    with pytest.raises(ValidationFailed) as excinfo:
        load_inputs(directory, date(2024, 6, 30))
    assert any("needs a calendar_id" in str(error) for error in excinfo.value.errors)


def test_unknown_calendar_is_rejected(tmp_path: Path) -> None:
    directory = _master_with(tmp_path, {"business_day_conv": "FOLLOWING", "calendar_id": "XX"})
    with pytest.raises(ValidationFailed) as excinfo:
        load_inputs(directory, date(2024, 6, 30))
    assert any("calendar 'XX' is not in" in str(error) for error in excinfo.value.errors)
