import csv
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from accrual.batch import run_batch
from accrual.calendar import adjust_payment_date, cash_dates

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
US = frozenset({date(2024, 7, 4), date(2024, 1, 1)})


def test_following_moves_a_saturday_to_monday() -> None:
    assert adjust_payment_date(date(2024, 6, 15), "FOLLOWING", US) == date(2024, 6, 17)


def test_following_skips_a_holiday() -> None:
    assert adjust_payment_date(date(2024, 7, 4), "FOLLOWING", US) == date(2024, 7, 5)


def test_preceding_moves_a_saturday_to_friday() -> None:
    assert adjust_payment_date(date(2024, 6, 29), "PRECEDING", US) == date(2024, 6, 28)


def test_modified_following_stays_in_month_when_following_does() -> None:
    assert adjust_payment_date(date(2024, 7, 4), "MODIFIED_FOLLOWING", US) == date(2024, 7, 5)


def test_modified_following_falls_back_when_following_crosses_month() -> None:
    assert adjust_payment_date(date(2024, 6, 30), "MODIFIED_FOLLOWING", US) == date(2024, 6, 28)


def test_business_days_are_unchanged() -> None:
    assert adjust_payment_date(date(2024, 7, 15), "FOLLOWING", US) == date(2024, 7, 15)


def test_cash_dates_keep_contract_dates_without_a_convention() -> None:
    security = SimpleNamespace(business_day_convention=None, calendar_id=None)
    pairs = cash_dates(security, {}, [date(2024, 6, 15)])
    assert pairs == [(date(2024, 6, 15), date(2024, 6, 15))]


def test_batch_writes_cash_schedule_with_adjusted_dates(tmp_path: Path) -> None:
    for source in SAMPLES.iterdir():
        shutil.copy(source, tmp_path / source.name)
    master = tmp_path / "security_master.csv"
    rows = list(csv.DictReader(master.open(encoding="utf-8", newline="")))
    fields = list(rows[0].keys())
    for row in rows:
        if row["security_id"] == "SAMPLE0001":
            row["business_day_conv"] = "FOLLOWING"
            row["calendar_id"] = "US"
    with master.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (tmp_path / "trades.csv").write_text(
        (SAMPLES / "trades.csv").read_text(encoding="utf-8").split("\n")[0] + "\n", encoding="utf-8"
    )
    run_batch(tmp_path, tmp_path / "out.csv", date(2024, 6, 30))
    schedule = list(csv.DictReader((tmp_path / "cash_schedule.csv").open(encoding="utf-8")))
    sample1 = [row for row in schedule if row["security_id"] == "SAMPLE0001"]
    assert sample1 and all(row["business_day_convention"] == "FOLLOWING" for row in sample1)
    for row in sample1:
        assert date.fromisoformat(row["cash_pay_date"]).weekday() < 5
