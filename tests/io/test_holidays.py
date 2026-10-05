import shutil
from datetime import date
from pathlib import Path

import pytest

from accrual.io.loaders import load_inputs
from accrual.io.parsing import ValidationFailed

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def test_holiday_calendar_is_loaded_by_calendar_id() -> None:
    inputs = load_inputs(SAMPLES, date(2024, 6, 30))
    assert date(2024, 2, 19) in inputs.holidays["US"]
    assert date(2024, 2, 9) in inputs.holidays["KR"]


def test_duplicate_holiday_is_reported(tmp_path: Path) -> None:
    for source in SAMPLES.iterdir():
        shutil.copy(source, tmp_path / source.name)
    calendar = tmp_path / "holiday_calendar.csv"
    calendar.write_text(calendar.read_text(encoding="utf-8") + "US,2024-01-01\n", encoding="utf-8")
    with pytest.raises(ValidationFailed) as excinfo:
        load_inputs(tmp_path, date(2024, 6, 30))
    assert any("duplicate holiday" in str(error) for error in excinfo.value.errors)
