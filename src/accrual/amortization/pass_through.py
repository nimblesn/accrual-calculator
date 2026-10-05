from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from accrual.accrual.accrued_interest import DailyAccrual, accrued_balance_rated, daily_accrual_series
from accrual.accrual.pass_through import PoolFactor, period_balances
from accrual.amortization.eir_solver import present_value, solve_periodic_eir
from accrual.daycount.types import get_day_count
from accrual.models.bond import PassThroughBond
from accrual.models.period import AccrualPeriod, ProjectionVersion
from accrual.models.result import AmortizationResult, AmortizationRow
from accrual.rounding import RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod

_ONE_DAY = timedelta(days=1)
PROSPECTIVE = "PROSPECTIVE"
CATCH_UP = "CATCH_UP"
PROJECTION_CHANGE_METHODS = (PROSPECTIVE, CATCH_UP)
_UNIT_FACE = Decimal(1)
DailyFn = Callable[[date, date], list[DailyAccrual]]


@dataclass(frozen=True)
class OpeningState:
    dirty: Decimal
    rate: Decimal


def pass_through_amortization(
    bond: PassThroughBond,
    factors: list[PoolFactor],
    projections: list[ProjectionVersion],
    settlement: date,
    face_amount: Decimal,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
    change_method: str = PROSPECTIVE,
) -> AmortizationResult:
    """MBS/ABS: a new projection version is handled by change_method (spec 9.5, default PROSPECTIVE)."""
    if not bond.dated_date <= settlement < end <= bond.maturity_date:
        raise ValueError("require dated_date <= settlement < end <= maturity_date")
    rated = period_balances(bond, factors)
    accrued0 = RoundingPolicy.round_amount(
        accrued_balance_rated(rated, _UNIT_FACE, bond.day_count_code, bond.coupon_freq, settlement),
        bond.currency,
    )

    def daily(start: date, stop: date) -> list[DailyAccrual]:
        return daily_accrual_series(
            rated, _UNIT_FACE, bond.currency, bond.day_count_code, bond.coupon_freq, start, stop
        )

    return projected_cash_amortization(
        currency=bond.currency,
        day_count_code=bond.day_count_code,
        coupon_freq=bond.coupon_freq,
        periods=[period for period, _ in rated],
        daily=daily,
        accrued_at_settlement=accrued0,
        face_amount=face_amount,
        clean_price=clean_price,
        transaction_cost=transaction_cost,
        projections=projections,
        settlement=settlement,
        end=end,
        change_method=change_method,
    )


def projected_cash_amortization(
    *,
    currency: str,
    day_count_code: str,
    coupon_freq: int,
    periods: list[CouponPeriod],
    daily: DailyFn,
    accrued_at_settlement: Decimal,
    face_amount: Decimal,
    clean_price: Decimal,
    transaction_cost: Decimal,
    projections: list[ProjectionVersion],
    settlement: date,
    end: date,
    opening: OpeningState | None = None,
    change_method: str = CATCH_UP,
) -> AmortizationResult:
    """Daily amortized cost from projected cash flows.

    When a later projection version takes effect:
    - CATCH_UP keeps the EIR and revalues the remaining flows at it, so the carrying amount jumps.
    - PROSPECTIVE keeps the carrying amount: on the effective date a new EIR is solved so that the new
      version's remaining flows are worth what the old version's flows were worth at the old EIR.
    """
    if change_method not in PROJECTION_CHANGE_METHODS:
        raise ValueError(f"unknown projection change method: {change_method}")
    day_count = get_day_count(day_count_code)
    freq = coupon_freq
    versions = sorted(projections, key=lambda v: v.effective_date)
    dirty_at_acquisition = (
        opening.dirty if opening is not None
        else face_amount * clean_price / 100 + transaction_cost + accrued_at_settlement
    )

    def active_flows(on: date) -> tuple:
        applicable = [v for v in versions if v.effective_date <= on]
        if not applicable:
            raise ValueError(f"no projected cash flows effective on or before {on}")
        return applicable[-1].flows

    axis = _TimeAxis(periods, day_count, freq)

    def discounted(on: date, flows: tuple) -> list[tuple[Decimal, Decimal]]:
        return [
            (cash.total, axis.tau(cash.pay_date) - axis.tau(on))
            for cash in flows
            if cash.pay_date > on
        ]

    if opening is not None:
        rate = opening.rate
    else:
        rate = solve_periodic_eir(discounted(settlement, active_flows(settlement)), dirty_at_acquisition)

    # (effective date, rate) in date order; the first entry covers everything up to the first change.
    rates: list[tuple[date, Decimal]] = [(settlement, rate)]
    if change_method == PROSPECTIVE:
        for effective in sorted({v.effective_date for v in versions if settlement < v.effective_date <= end}):
            previous_rate = rates[-1][1]
            carrying = present_value(discounted(effective, active_flows(effective - _ONE_DAY)), previous_rate)
            remaining = discounted(effective, active_flows(effective))
            if not remaining:
                raise ValueError(f"projection effective {effective} has no cash flows after that date")
            rates.append((effective, solve_periodic_eir(remaining, carrying)))

    def rate_on(on: date) -> Decimal:
        applicable = [r for since, r in rates if since <= on]
        return applicable[-1] if applicable else rates[0][1]

    dirty_cache: dict[date, Decimal] = {}

    def dirty_at(on: date) -> Decimal:
        if on not in dirty_cache:
            dirty_cache[on] = present_value(discounted(on, active_flows(on)), rate_on(on))
        return dirty_cache[on]

    last_cash_date = max(cash.pay_date for version in versions for cash in version.flows)

    rows: list[AmortizationRow] = []
    for accrual in daily(settlement + _ONE_DAY, end):
        on = accrual.on
        previous = on - _ONE_DAY
        cash_on = sum(
            (cash.total for cash in active_flows(previous) if cash.pay_date == on), Decimal(0)
        )
        dirty_now = dirty_at(on)
        interest_income = (
            RoundingPolicy.round_amount(dirty_now, currency)
            - RoundingPolicy.round_amount(dirty_at(previous), currency)
            + RoundingPolicy.round_amount(cash_on, currency)
        )
        if on == last_cash_date:
            principal_due = sum(
                (cash.principal for cash in active_flows(previous) if cash.pay_date == on), Decimal(0)
            )
            book = RoundingPolicy.round_amount(principal_due, currency)
        else:
            book = RoundingPolicy.round_amount(dirty_now, currency) - accrual.accrued_cum
        rows.append(
            AmortizationRow(
                on=on,
                amortized_cost=book,
                accrued_cum=accrual.accrued_cum,
                accrued_daily=accrual.accrued_daily,
                interest_income=interest_income,
                amortization=interest_income - accrual.accrued_daily,
                eir_periodic=rate_on(on),
            )
        )

    current = rate_on(rows[-1].on) if rows else rate
    return AmortizationResult(
        eir_periodic=current,
        eir_annual=(1 + current) ** freq - 1,
        rows=rows,
    )


class _TimeAxis:
    def __init__(self, periods: list[CouponPeriod], day_count, freq: int) -> None:
        self._periods = periods
        self._day_count = day_count
        self._freq = freq
        self._cache: dict[date, Decimal] = {}

    def tau(self, on: date) -> Decimal:
        if on not in self._cache:
            self._cache[on] = self._compute(on)
        return self._cache[on]

    def _compute(self, on: date) -> Decimal:
        for index, period in enumerate(self._periods):
            if period.start <= on < period.end:
                return Decimal(index) + _ratio(period, period.start, on, self._day_count, self._freq)
        last = self._periods[-1]
        if on >= last.end:
            extra = _ratio(last, last.end, on, self._day_count, self._freq)
            return Decimal(len(self._periods) - 1) + Decimal(1) + extra
        return Decimal(0)


def _ratio(period: CouponPeriod, low: date, high: date, day_count, freq: int) -> Decimal:
    accrual_period = AccrualPeriod(period.start, period.end, freq)
    numerator = day_count.year_fraction(low, high, accrual_period)
    denominator = day_count.year_fraction(period.start, period.end, accrual_period)
    return numerator / denominator
