import calendar
from dataclasses import dataclass
from datetime import date
from enum import Enum

_SUPPORTED_FREQS = (1, 2, 4, 12)


class StubType(Enum):
    SHORT = "SHORT"
    LONG = "LONG"


@dataclass(frozen=True)
class CouponPeriod:
    start: date
    end: date
    pay_date: date


def generate_coupon_schedule(
    *,
    issue_date: date,
    dated_date: date,
    maturity_date: date,
    first_coupon_date: date | None,
    coupon_freq: int,
    end_of_month: bool,
    last_stub: StubType = StubType.SHORT,
) -> list[CouponPeriod]:
    _validate(issue_date, dated_date, maturity_date, first_coupon_date, coupon_freq)

    if coupon_freq == 0:
        return [CouponPeriod(dated_date, maturity_date, maturity_date)]

    step_months = 12 // coupon_freq
    anchor = first_coupon_date if first_coupon_date is not None else dated_date
    grid, next_regular = _regular_dates_before(anchor, maturity_date, step_months, end_of_month)
    interior = [d for d in grid if d > dated_date]

    if last_stub is StubType.LONG and interior and next_regular != maturity_date:
        interior = interior[:-1]

    points = [dated_date, *interior, maturity_date]
    return [CouponPeriod(start, end, end) for start, end in zip(points, points[1:])]


def find_period(periods: list[CouponPeriod], on: date) -> CouponPeriod:
    for period in periods:
        if period.start <= on < period.end:
            return period
    raise ValueError(f"no coupon period contains {on}")


def _validate(
    issue_date: date,
    dated_date: date,
    maturity_date: date,
    first_coupon_date: date | None,
    coupon_freq: int,
) -> None:
    if coupon_freq == 0:
        if first_coupon_date is not None:
            raise ValueError("zero coupon bond must not have a first coupon date")
    elif coupon_freq not in _SUPPORTED_FREQS:
        raise ValueError(f"unsupported coupon frequency: {coupon_freq}")

    if not issue_date <= dated_date < maturity_date:
        raise ValueError("require issue_date <= dated_date < maturity_date")
    if first_coupon_date is not None and not dated_date <= first_coupon_date <= maturity_date:
        raise ValueError("first coupon date must be between dated date and maturity")


def _regular_dates_before(
    anchor: date, maturity: date, step_months: int, end_of_month: bool
) -> tuple[list[date], date]:
    dates: list[date] = []
    index = 0
    while True:
        candidate = _nth_date(anchor, index * step_months, end_of_month)
        if candidate >= maturity:
            return dates, candidate
        dates.append(candidate)
        index += 1


def _nth_date(anchor: date, months: int, end_of_month: bool) -> date:
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    anchor_is_month_end = anchor.day == calendar.monthrange(anchor.year, anchor.month)[1]
    if end_of_month and anchor_is_month_end:
        return date(year, month, last_day)
    return date(year, month, min(anchor.day, last_day))
