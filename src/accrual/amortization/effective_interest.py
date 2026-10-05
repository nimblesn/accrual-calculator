from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from accrual.accrual.accrued_interest import (
    RatedPeriod,
    accrued_balance_rated,
    cumulative_rated,
    daily_accrual_series,
)
from accrual.accrual.floating import Fixing, rated_periods
from accrual.amortization.eir_solver import solve_periodic_eir
from accrual.daycount.types import get_day_count
from accrual.models.bond import FixedRateBond, FloatingRateBond
from accrual.models.period import AccrualPeriod
from accrual.models.result import AmortizationResult, AmortizationRow
from accrual.rounding import RoundingPolicy
from accrual.schedule.coupon_schedule import CouponPeriod

_ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class _Terms:
    currency: str
    day_count_code: str
    coupon_freq: int
    dated: date
    maturity: date


def fixed_rate_amortization(
    bond: FixedRateBond,
    face: Decimal,
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
) -> AmortizationResult:
    _require_coupon_bond(bond.coupon_freq)
    _require_range(bond.dated_date, bond.maturity_date, settlement, end)
    rated = [(period, bond.coupon_rate) for period in bond.schedule()]
    return _amortize(
        _terms(bond), face, rated, face * bond.redemption_price / 100,
        settlement, clean_price, transaction_cost, end, resolve_each_period=False,
    )


def floating_amortization(
    bond: FloatingRateBond,
    face: Decimal,
    fixings: list[Fixing],
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
) -> AmortizationResult:
    _require_coupon_bond(bond.coupon_freq)
    _require_range(bond.dated_date, bond.maturity_date, settlement, end)
    rated = rated_periods(bond, fixings)
    return _amortize(
        _terms(bond), face, rated, face * bond.redemption_price / 100,
        settlement, clean_price, transaction_cost, end, resolve_each_period=True,
    )


def _terms(bond: FixedRateBond | FloatingRateBond) -> _Terms:
    return _Terms(
        currency=bond.currency,
        day_count_code=bond.day_count_code,
        coupon_freq=bond.coupon_freq,
        dated=bond.dated_date,
        maturity=bond.maturity_date,
    )


def _amortize(
    terms: _Terms,
    face: Decimal,
    rated: list[RatedPeriod],
    redemption: Decimal,
    settlement: date,
    clean_price: Decimal,
    transaction_cost: Decimal,
    end: date,
    resolve_each_period: bool,
) -> AmortizationResult:
    currency = terms.currency
    day_count_code = terms.day_count_code
    freq = terms.coupon_freq
    accrued_at_acquisition = RoundingPolicy.round_amount(
        accrued_balance_rated(rated, face, day_count_code, freq, settlement), currency
    )
    dirty_at_acquisition = face * clean_price / 100 + transaction_cost + accrued_at_acquisition

    future = [i for i, (period, _) in enumerate(rated) if period.end > settlement]
    first_fraction = _fraction(day_count_code, freq, settlement, rated[future[0]][0].end, rated[future[0]][0])
    coupons = [
        cumulative_rated(face, rate, day_count_code, freq, period, period.end)
        for period, rate in (rated[i] for i in future)
    ]
    count = len(future)

    def flows_from(j: int) -> list[tuple[Decimal, Decimal]]:
        rate = rated[future[j]][1]
        flows = []
        for m in range(j, count):
            period = rated[future[m]][0]
            amount = cumulative_rated(face, rate, day_count_code, freq, period, period.end)
            if m == count - 1:
                amount += redemption
            fraction = first_fraction if j == 0 else Decimal(1)
            flows.append((amount, fraction + (m - j)))
        return flows

    bases = [dirty_at_acquisition]
    rates_by_period: list[Decimal] = []
    for j in range(count):
        if j == 0 or resolve_each_period:
            rate_j = solve_periodic_eir(flows_from(j), bases[j])
        else:
            rate_j = rates_by_period[0]
        rates_by_period.append(rate_j)
        if j < count - 1:
            growth = (1 + rate_j) ** (first_fraction if j == 0 else Decimal(1))
            bases.append(bases[j] * growth - coupons[j])

    def dirty_at(on: date) -> Decimal:
        for j, index in enumerate(future):
            period = rated[index][0]
            if period.start <= on < period.end:
                if j == 0:
                    base = dirty_at_acquisition
                    fraction = _fraction(day_count_code, freq, settlement, on, period)
                else:
                    base = bases[j]
                    fraction = _fraction(day_count_code, freq, period.start, on, period)
                return base * (1 + rates_by_period[j]) ** fraction
        return Decimal(0)

    cash_on: dict[date, Decimal] = {rated[index][0].end: coupons[j] for j, index in enumerate(future)}
    cash_on[terms.maturity] = cash_on.get(terms.maturity, Decimal(0)) + redemption

    rows: list[AmortizationRow] = []
    for daily in daily_accrual_series(
        rated, face, currency, day_count_code, freq, settlement + _ONE_DAY, end
    ):
        on = daily.on
        dirty_now = dirty_at(on)
        dirty_before = dirty_at(on - _ONE_DAY)
        interest_income = (
            RoundingPolicy.round_amount(dirty_now, currency)
            - RoundingPolicy.round_amount(dirty_before, currency)
            + RoundingPolicy.round_amount(cash_on.get(on, Decimal(0)), currency)
        )
        if on == terms.maturity:
            amortized_cost = RoundingPolicy.round_amount(redemption, currency)
        else:
            amortized_cost = RoundingPolicy.round_amount(dirty_now, currency) - daily.accrued_cum
        income_index = _income_period_index(future, rated, on)
        rows.append(
            AmortizationRow(
                on=on,
                amortized_cost=amortized_cost,
                accrued_cum=daily.accrued_cum,
                accrued_daily=daily.accrued_daily,
                interest_income=interest_income,
                amortization=interest_income - daily.accrued_daily,
                eir_periodic=rates_by_period[income_index],
            )
        )

    initial_rate = rates_by_period[0]
    return AmortizationResult(
        eir_periodic=initial_rate,
        eir_annual=(1 + initial_rate) ** freq - 1,
        rows=rows,
    )


def _income_period_index(future: list[int], rated: list[RatedPeriod], on: date) -> int:
    for j, index in enumerate(future):
        period = rated[index][0]
        if period.start < on <= period.end:
            return j
    return len(future) - 1


def _fraction(
    day_count_code: str, freq: int, start: date, on: date, period: CouponPeriod
) -> Decimal:
    day_count = get_day_count(day_count_code)
    accrual_period = AccrualPeriod(period.start, period.end, freq)
    numerator = day_count.year_fraction(start, on, accrual_period)
    denominator = day_count.year_fraction(period.start, period.end, accrual_period)
    return numerator / denominator


def _require_coupon_bond(freq: int) -> None:
    if freq == 0:
        raise ValueError("zero coupon bonds use straight-line amortization")


def _require_range(dated: date, maturity: date, settlement: date, end: date) -> None:
    if not dated <= settlement < end <= maturity:
        raise ValueError("require dated_date <= settlement < end <= maturity_date")
