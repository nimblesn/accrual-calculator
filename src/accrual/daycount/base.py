from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal, localcontext

from accrual.models.period import AccrualPeriod
from accrual.rounding import WORKING_PRECISION


class UnsupportedDayCountError(ValueError):
    pass


def validate_interval(start: date, end: date) -> None:
    if end < start:
        raise ValueError(f"interval end before start: {start} -> {end}")


def ratio(numerator: int, denominator: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = WORKING_PRECISION
        return Decimal(numerator) / Decimal(denominator)


class DayCountConvention(ABC):
    @abstractmethod
    def day_count(self, start: date, end: date) -> int: ...

    @abstractmethod
    def year_fraction(self, start: date, end: date, period: AccrualPeriod) -> Decimal: ...
