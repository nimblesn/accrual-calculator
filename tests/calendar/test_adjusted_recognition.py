import csv
import shutil
from datetime import date
from pathlib import Path

from accrual.batch import run_batch

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
END = date(2024, 9, 30)


def _run(target: Path, convention: str | None) -> dict[str, dict[str, str]]:
    target.mkdir(parents=True)
    for source in SAMPLES.iterdir():
        shutil.copy(source, target / source.name)
    master = target / "security_master.csv"
    rows = list(csv.DictReader(master.open(encoding="utf-8", newline="")))
    fields = list(rows[0].keys())
    for row in rows:
        if row["security_id"] == "SAMPLE0003":
            row["business_day_conv"] = convention or ""
            row["calendar_id"] = "KR" if convention else ""
    with master.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    lines = (SAMPLES / "trades.csv").read_text(encoding="utf-8").splitlines()
    kept = [lines[0]] + [line for line in lines[1:] if line.startswith("T0004,")]
    (target / "trades.csv").write_text("\n".join(kept) + "\n", encoding="utf-8")
    out = target / "out.csv"
    run_batch(target, out, END)
    with out.open(encoding="utf-8", newline="") as handle:
        return {row["date"]: row for row in csv.DictReader(handle) if row["lot_id"] == "L0004"}


def test_coupon_on_weekend_is_booked_as_receivable_until_paid(tmp_path: Path) -> None:
    rows = _run(tmp_path / "adjusted", "FOLLOWING")
    contract_day = rows["2024-08-10"]
    assert contract_day["accrued_interest_cum"] == "0.00"
    before = float(rows["2024-08-09"]["amortized_cost"])
    while_receivable = float(rows["2024-08-11"]["amortized_cost"])
    after_cash = float(rows["2024-08-13"]["amortized_cost"])
    assert while_receivable - before > 3_000_000
    assert before - after_cash < 0
    assert abs(after_cash - before) < 10_000


def test_cash_day_shows_no_spike_in_income(tmp_path: Path) -> None:
    rows = _run(tmp_path / "adjusted", "FOLLOWING")
    neighbour = float(rows["2024-08-11"]["interest_income"])
    cash_day = float(rows["2024-08-12"]["interest_income"])
    assert abs(cash_day - neighbour) < 10


def test_adjustment_changes_eir_only_slightly(tmp_path: Path) -> None:
    contract = _run(tmp_path / "contract", None)
    adjusted = _run(tmp_path / "adjusted", "FOLLOWING")
    eir_contract = float(contract["2024-03-01"]["eir"])
    eir_adjusted = float(adjusted["2024-03-01"]["eir"])
    assert eir_adjusted != eir_contract
    assert abs(eir_adjusted - eir_contract) < 1e-5
