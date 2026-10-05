from datetime import date, timedelta

from accrual.io.loaders import Security


def is_business_day(day: date, holidays: frozenset[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def adjust_payment_date(day: date, convention: str, holidays: frozenset[date]) -> date:
    if convention == "PRECEDING":
        return _preceding(day, holidays)
    following = _following(day, holidays)
    if convention == "MODIFIED_FOLLOWING" and following.month != day.month:
        return _preceding(day, holidays)
    return following


def _following(day: date, holidays: frozenset[date]) -> date:
    current = day
    while not is_business_day(current, holidays):
        current += timedelta(days=1)
    return current


def _preceding(day: date, holidays: frozenset[date]) -> date:
    current = day
    while not is_business_day(current, holidays):
        current -= timedelta(days=1)
    return current


def cash_dates(security: Security, holidays: dict[str, frozenset[date]], contract_dates: list[date]) -> list[tuple[date, date]]:
    if security.business_day_convention is None:
        return [(day, day) for day in contract_dates]
    calendar = holidays[security.calendar_id]
    return [
        (day, adjust_payment_date(day, security.business_day_convention, calendar))
        for day in contract_dates
    ]
