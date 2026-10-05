import argparse
import sys
from datetime import date
from pathlib import Path

from accrual.amortization.pass_through import PROJECTION_CHANGE_METHODS, PROSPECTIVE
from accrual.batch import run_batch
from accrual.io.parsing import ValidationFailed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="accrual", description="Batch accrual and amortization")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--calc-end", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--projection-change", choices=PROJECTION_CHANGE_METHODS, default=PROSPECTIVE,
        help="MBS/ABS projection version change: PROSPECTIVE re-solves the EIR (default), CATCH_UP revalues",
    )
    parser.add_argument(
        "--snapshot-dates", default="", type=_parse_dates,
        help="comma-separated YYYY-MM-DD dates to write to snapshot.csv beside the output",
    )
    args = parser.parse_args(argv)
    try:
        report = run_batch(args.input_dir, args.output, args.calc_end, args.snapshot_dates, args.projection_change)
    except ValidationFailed as failure:
        for error in failure.errors:
            print(f"error: {error}", file=sys.stderr)
        print(f"{len(failure.errors)} validation error(s); no output written", file=sys.stderr)
        return 1
    for warning in report.warnings:
        print(f"warning: {warning}")
    print(f"{report.lots} lot(s), {report.rows} row(s) written to {report.output}")
    if report.snapshot is not None:
        print(f"{report.snapshot_rows} snapshot row(s) written to {report.snapshot}")
        for day in report.missing_snapshot_dates:
            print(f"warning: no rows on snapshot date {day.isoformat()}")
    return 0


def _parse_dates(value: str) -> tuple[date, ...]:
    if not value:
        return ()
    return tuple(date.fromisoformat(part.strip()) for part in value.split(",") if part.strip())


if __name__ == "__main__":
    raise SystemExit(main())
