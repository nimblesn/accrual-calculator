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


def test_snapshot_rows_match_full_output_on_requested_dates(tmp_path: Path) -> None:
    import csv

    out = tmp_path / "out.csv"
    wanted = (date(2024, 3, 31), date(2024, 5, 22))
    report = run_batch(SAMPLES, out, CALC_END, wanted)

    assert report.snapshot == tmp_path / "snapshot.csv"
    assert report.missing_snapshot_dates == ()
    full = [row for row in csv.DictReader(out.open(encoding="utf-8")) if row["date"] in {d.isoformat() for d in wanted}]
    snap = list(csv.DictReader(report.snapshot.open(encoding="utf-8")))
    assert report.snapshot_rows == len(snap) == len(full)
    assert snap == full


def test_snapshot_reports_dates_outside_the_window(tmp_path: Path) -> None:
    report = run_batch(SAMPLES, tmp_path / "out.csv", CALC_END, (date(2030, 1, 1),))
    assert report.snapshot_rows == 0
    assert report.missing_snapshot_dates == (date(2030, 1, 1),)
