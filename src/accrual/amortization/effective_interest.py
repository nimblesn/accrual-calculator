from collections.abc import Callable
from datetime import date
from decimal import Decimal

from accrual.accrual.accrued_interest import accrued_balance_rated, cumulative_rated, daily_accrual_series
from accrual.accrual.floating import Fixing, index_rate_on, rated_periods
from accrual.amortization.pass_through import OpeningState, projected_cash_amortization
from accrual.models.bond import FixedRateBond, FloatingRateBond
from accrual.models.period import CashFlow, ProjectionVersion
from accrual.models.result import AmortizationResult
from accrual.rounding import RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod

PayDate = Callable[[date], date]


def _identity(day: date) -> date:
    return day


def fixed_rate_amortization(
    bond: FixedRateBond,
    face: Decimal,
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
    opening: OpeningState | None = None,
    pay_date: PayDate = _identity,
) -> AmortizationResult:
    _require_coupon_bond(bond.coupon_freq)
    _require_range(bond.dated_date, bond.maturity_date, settlement, end)
    rated = [(period, bond.coupon_rate) for period in bond.schedule()]
    redemption = face * bond.redemption_price / 100
    flows = _flows(bond, face, rated, redemption, pay_date, after=None)
    versions = [ProjectionVersion(1, settlement, tuple(flows))]
    return _run(bond, face, rated, versions, settlement, clean_price, transaction_cost, end, opening)


def floating_amortization(
    bond: FloatingRateBond,
    face: Decimal,
    fixings: list[Fixing],
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
    opening: OpeningState | None = None,
    pay_date: PayDate = _identity,
) -> AmortizationResult:
    _require_coupon_bond(bond.coupon_freq)
    _require_range(bond.dated_date, bond.maturity_date, settlement, end)
    rated = rated_periods(bond, fixings)
    periods = [period for period, _ in rated]
    redemption = face * bond.redemption_price / 100
    versions: list[ProjectionVersion] = []
    for number, reset in enumerate((period.start for period in periods), start=1):
        known = [
            (period, bond.coupon_rate(index_rate_on(bond, fixings, min(period.start, reset))))
            for period in periods
        ]
        flows = _flows(bond, face, known, redemption, pay_date, after=reset)
        versions.append(ProjectionVersion(number, reset, tuple(flows)))
    return _run(bond, face, rated, versions, settlement, clean_price, transaction_cost, end, opening)


def _flows(
    bond,
    face: Decimal,
    rated: list[tuple[CouponPeriod, Decimal]],
    redemption: Decimal,
    pay_date: PayDate,
    after: date | None,
) -> list[CashFlow]:
    flows: list[CashFlow] = []
    last = len(rated) - 1
    for index, (period, rate) in enumerate(rated):
        pay = pay_date(period.end)
        if after is not None and pay <= after:
            continue
        coupon = cumulative_rated(face, rate, bond.day_count_code, bond.coupon_freq, period, period.end)
        principal = redemption if index == last else Decimal(0)
        flows.append(CashFlow(pay, principal, coupon))
    return flows


def _run(
    bond,
    face: Decimal,
    rated: list[tuple[CouponPeriod, Decimal]],
    versions: list[ProjectionVersion],
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
    opening: OpeningState | None,
) -> AmortizationResult:
    currency = bond.currency
    day_count_code = bond.day_count_code
    freq = bond.coupon_freq
    accrued0 = RoundingPolicy.round_amount(
        accrued_balance_rated(rated, face, day_count_code, freq, settlement), currency
    )

    def daily(start: date, stop: date):
        return daily_accrual_series(rated, face, currency, day_count_code, freq, start, stop)

    return projected_cash_amortization(
        currency=currency,
        day_count_code=day_count_code,
        coupon_freq=freq,
        periods=[period for period, _ in rated],
        daily=daily,
        accrued_at_settlement=accrued0,
        face_amount=face,
        clean_price=clean_price,
        transaction_cost=transaction_cost,
        projections=versions,
        settlement=settlement,
        end=end,
        opening=opening,
    )


def _require_coupon_bond(freq: int) -> None:
    if freq == 0:
        raise ValueError("zero coupon bonds use straight-line amortization")


def _require_range(dated: date, maturity: date, settlement: date, end: date) -> None:
    if not dated <= settlement < end <= maturity:
        raise ValueError("require dated_date <= settlement < end <= maturity_date")
