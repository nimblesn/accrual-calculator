import argparse
import sys
from datetime import date
from pathlib import Path

from accrual.batch import run_batch
from accrual.io.parsing import ValidationFailed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="accrual", description="Batch accrual and amortization")
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--calc-end", required=True, type=date.fromisoformat)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_batch(args.input_dir, args.output, args.calc_end)
    except ValidationFailed as failure:
        for error in failure.errors:
            print(f"error: {error}", file=sys.stderr)
        print(f"{len(failure.errors)} validation error(s); no output written", file=sys.stderr)
        return 1
    for warning in report.warnings:
        print(f"warning: {warning}")
    print(f"{report.lots} lot(s), {report.rows} row(s) written to {report.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
