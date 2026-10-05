from enum import Enum

from accrual.daycount import conventions as c
from accrual.daycount.base import DayCountConvention, UnsupportedDayCountError


class DayCountType(Enum):
    D30_360 = "D30/360"
    E30_360 = "30E/360"
    P30_360 = "30P/360"
    NL_365 = "NL/365"
    ACT_365 = "ACT/365"
    ACT_360 = "ACT/360"
    ACT_AFB = "ACT/AFB"
    ACT_TSY = "ACT/TSY"
    ACT_ACT = "ACT/ACT"
    ACT_366 = "ACT/366"


_CONVENTIONS: dict[DayCountType, DayCountConvention] = {
    DayCountType.D30_360: c.Thirty360BondBasis(),
    DayCountType.E30_360: c.Thirty360Eurobond(),
    DayCountType.P30_360: c.Thirty360BondBasis(),
    DayCountType.NL_365: c.NoLeapDay365(),
    DayCountType.ACT_365: c.Actual365Fixed(),
    DayCountType.ACT_360: c.Actual360(),
    DayCountType.ACT_AFB: c.ActualAfb(),
    DayCountType.ACT_TSY: c.ActualTsy(),
    DayCountType.ACT_ACT: c.ActualActIsda(),
    DayCountType.ACT_366: c.Actual366(),
}


def get_day_count(code: str) -> DayCountConvention:
    try:
        day_count_type = DayCountType(code)
    except ValueError:
        raise UnsupportedDayCountError(f"unsupported day count code: {code!r}") from None
    return _CONVENTIONS[day_count_type]
