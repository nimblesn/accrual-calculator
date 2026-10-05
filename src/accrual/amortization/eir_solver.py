from collections.abc import Sequence
from decimal import Decimal, localcontext

from accrual.rounding import WORKING_PRECISION

_TOLERANCE = Decimal("1E-12")
_MAX_NEWTON_STEPS = 100
_BISECTION_LOWER = Decimal("-0.99")
_BISECTION_UPPER = Decimal(10)


def solve_periodic_eir(flows: Sequence[tuple[Decimal, Decimal]], target: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = WORKING_PRECISION
        root = _newton(flows, target)
        if root is not None:
            return root
        return _bisect(flows, target)


def _present_value(flows: Sequence[tuple[Decimal, Decimal]], rate: Decimal) -> Decimal:
    return sum((amount * (1 + rate) ** (-periods) for amount, periods in flows), Decimal(0))


def _present_value_slope(flows: Sequence[tuple[Decimal, Decimal]], rate: Decimal) -> Decimal:
    return sum(
        (-periods * amount * (1 + rate) ** (-periods - 1) for amount, periods in flows),
        Decimal(0),
    )


def _newton(flows: Sequence[tuple[Decimal, Decimal]], target: Decimal) -> Decimal | None:
    rate = Decimal("0.01")
    for _ in range(_MAX_NEWTON_STEPS):
        error = _present_value(flows, rate) - target
        slope = _present_value_slope(flows, rate)
        if slope == 0:
            return None
        candidate = rate - error / slope
        if candidate <= -1:
            return None
        if abs(candidate - rate) < _TOLERANCE:
            return candidate
        rate = candidate
    return None


def _bisect(flows: Sequence[tuple[Decimal, Decimal]], target: Decimal) -> Decimal:
    lower, upper = _BISECTION_LOWER, _BISECTION_UPPER
    lower_error = _present_value(flows, lower) - target
    upper_error = _present_value(flows, upper) - target
    if lower_error * upper_error > 0:
        raise ValueError("EIR root is not bracketed")
    while upper - lower > _TOLERANCE:
        middle = (lower + upper) / 2
        middle_error = _present_value(flows, middle) - target
        if middle_error * lower_error > 0:
            lower, lower_error = middle, middle_error
        else:
            upper = middle
    return (lower + upper) / 2
