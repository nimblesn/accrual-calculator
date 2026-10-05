from datetime import date
from decimal import Decimal

from accrual.daycount.base import DayCountConvention, ratio, validate_interval
from accrual.models.period import AccrualPeriod


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def _leap_days_between(start: date, end: date) -> int:
    count = 0
    for year in range(start.year, end.year + 1):
        if _is_leap_year(year) and start <= date(year, 2, 29) < end:
            count += 1
    return count


def _thirty_360_days(start: date, end: date, start_day: int, end_day: int) -> int:
    return 360 * (end.year - start.year) + 30 * (end.month - start.month) + (end_day - start_day)


class Thirty360BondBasis(DayCountConvention):
    def day_count(self, start: date, end: date) -> int:
        validate_interval(start, end)
        start_day = 30 if start.day == 31 else start.day
        end_day = 30 if end.day == 31 and start_day == 30 else end.day
        return _thirty_360_days(start, end, start_day, end_day)

    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal:
        return ratio(self.day_count(start, end), 360)


class Thirty360Eurobond(DayCountConvention):
    def day_count(self, start: date, end: date) -> int:
        validate_interval(start, end)
        start_day = 30 if start.day == 31 else start.day
        end_day = 30 if end.day == 31 else end.day
        return _thirty_360_days(start, end, start_day, end_day)

    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal:
        return ratio(self.day_count(start, end), 360)


class _ActualOverFixedBase(DayCountConvention):
    denominator: int

    def day_count(self, start: date, end: date) -> int:
        validate_interval(start, end)
        return (end - start).days

    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal:
        return ratio(self.day_count(start, end), self.denominator)


class Actual365Fixed(_ActualOverFixedBase):
    denominator = 365


class Actual360(_ActualOverFixedBase):
    denominator = 360


class Actual366(_ActualOverFixedBase):
    denominator = 366


class NoLeapDay365(DayCountConvention):
    def day_count(self, start: date, end: date) -> int:
        validate_interval(start, end)
        return (end - start).days - _leap_days_between(start, end)

    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal:
        return ratio(self.day_count(start, end), 365)


class ActualAfb(DayCountConvention):
    def day_count(self, start: date, end: date) -> int:
        validate_interval(start, end)
        return (end - start).days

    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal:
        validate_interval(start, end)
        whole_years = 0
        anchor = end
        while _add_years(anchor, -1) >= start:
            anchor = _add_years(anchor, -1)
            whole_years += 1
        stub_days = (anchor - start).days
        denominator = 366 if _leap_days_between(start, anchor) else 365
        return Decimal(whole_years) + ratio(stub_days, denominator)


class ActualTsy(DayCountConvention):
    def day_count(self, start: date, end: date) -> int:
        validate_interval(start, end)
        return (end - start).days

    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal:
        validate_interval(start, end)
        period_days = (period.end - period.start).days
        return ratio(self.day_count(start, end), period_days * period.coupon_freq)


class ActualActIsda(DayCountConvention):
    def day_count(self, start: date, end: date) -> int:
        validate_interval(start, end)
        return (end - start).days

    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal:
        validate_interval(start, end)
        total = Decimal(0)
        for year in range(start.year, end.year + 1):
            segment_start = max(start, date(year, 1, 1))
            segment_end = min(end, date(year + 1, 1, 1))
            if segment_start < segment_end:
                denominator = 366 if _is_leap_year(year) else 365
                total += ratio((segment_end - segment_start).days, denominator)
        return total
