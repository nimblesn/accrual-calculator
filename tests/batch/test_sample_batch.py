from datetime import date
from pathlib import Path

from accrual.batch import run_batch

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
CALC_END = date(2024, 6, 30)


def test_full_sample_batch_covers_every_lot_and_term(tmp_path: Path) -> None:
    report = run_batch(SAMPLES, tmp_path / "out.csv", CALC_END)

    assert report.lots == 8
    assert report.warnings == []
    expected_rows = sum(
        (CALC_END - settlement).days
        for settlement in (
            date(2024, 2, 22), date(2024, 3, 12), date(2024, 3, 4), date(2024, 2, 16),
            date(2024, 4, 12), date(2024, 3, 20), date(2024, 3, 10), date(2024, 2, 20),
        )
    )
    assert report.rows == expected_rows
