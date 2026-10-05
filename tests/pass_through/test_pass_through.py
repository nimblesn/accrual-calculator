from datetime import date
from decimal import Decimal

from accrual.accrual.pass_through import PoolFactor, pass_through_accrued_on, period_balances
from accrual.amortization.eir_solver import present_value
from accrual.daycount.types import get_day_count
from accrual.amortization.pass_through import pass_through_amortization
from accrual.models.bond import PassThroughBond
from accrual.models.period import AccrualPeriod
from accrual.models.period import CashFlow, ProjectionVersion

# Terms mirror samples/security_master.csv SAMPLE0005 (MBS) and SAMPLE0006 (ABS).
MBS = PassThroughBond(
    security_id="SAMPLE0005",
    bond_type="MBS",
    currency="USD",
    issue_date=date(2024, 1, 1),
    dated_date=date(2024, 1, 1),
    maturity_date=date(2054, 1, 1),
    coupon_rate=Decimal("0.055"),
    coupon_freq=12,
    day_count_code="30P/360",
    end_of_month=False,
    original_face=Decimal("50000000"),
    payment_delay_days=24,
)
MBS_FACTORS = [
    PoolFactor(date(2024, 1, 1), Decimal("1.00000000")),
    PoolFactor(date(2024, 2, 1), Decimal("0.98000000")),
    PoolFactor(date(2024, 3, 1), Decimal("0.97500000")),
    PoolFactor(date(2024, 4, 1), Decimal("0.97000000")),
]

ABS = PassThroughBond(
    security_id="SAMPLE0006",
    bond_type="ABS",
    currency="USD",
    issue_date=date(2024, 1, 1),
    dated_date=date(2024, 1, 1),
    maturity_date=date(2034, 1, 1),
    coupon_rate=Decimal("0.06"),
    coupon_freq=12,
    day_count_code="30E/360",
    end_of_month=False,
    original_face=Decimal("20000000"),
    payment_delay_days=14,
)
ABS_FACTORS = [
    PoolFactor(date(2024, 1, 1), Decimal("1.00000000")),
    PoolFactor(date(2024, 3, 1), Decimal("0.99000000")),
    PoolFactor(date(2024, 4, 1), Decimal("0.98000000")),
]


def test_mbs_accrual_matches_trade_sample_t0006() -> None:
    assert pass_through_accrued_on(MBS, MBS_FACTORS, date(2024, 3, 20)) == Decimal("141510.42")


def test_abs_accrual_matches_trade_sample_t0007() -> None:
    assert pass_through_accrued_on(ABS, ABS_FACTORS, date(2024, 3, 10)) == Decimal("29700.00")


def test_factor_applies_from_the_period_it_becomes_effective() -> None:
    rated = period_balances(MBS, MBS_FACTORS)
    balances = {period.start: rate / Decimal("0.055") for period, rate in rated}
    assert balances[date(2024, 2, 1)] == Decimal("49000000")
    assert balances[date(2024, 3, 1)] == Decimal("48750000")


# Small deal used for amortization invariants: monthly flows, factor 1.
DEAL = PassThroughBond(
    security_id="DEAL",
    bond_type="ABS",
    currency="USD",
    issue_date=date(2024, 1, 1),
    dated_date=date(2024, 1, 1),
    maturity_date=date(2026, 1, 1),
    coupon_rate=Decimal("0.06"),
    coupon_freq=12,
    day_count_code="30E/360",
    end_of_month=False,
    original_face=Decimal("1000000"),
)
DEAL_FACTORS = [PoolFactor(date(2024, 1, 1), Decimal("1"))]


def _flows(interest: Decimal) -> tuple[CashFlow, ...]:
    months = [date(2024 + (k + 1) // 12, (k + 1) % 12 + 1, 25) for k in range(23)]
    principal = [Decimal("40000")] * 22 + [Decimal("120000")]
    return tuple(CashFlow(pay, principal[k], interest) for k, pay in enumerate(months))


def test_eir_discounts_projected_cash_flows_to_acquisition_price() -> None:
    result = pass_through_amortization(
        DEAL, DEAL_FACTORS, [ProjectionVersion(date(2024, 1, 1), _flows(Decimal("5000")))],
        date(2024, 1, 1), Decimal("1000000"), Decimal("100"), Decimal("0"), date(2025, 12, 31),
    )
    assert result.eir_periodic is not None
    assert result.eir_periodic > 0


def test_income_telescopes_to_cash_less_acquisition_cost() -> None:
    result = pass_through_amortization(
        DEAL, DEAL_FACTORS, [ProjectionVersion(date(2024, 1, 1), _flows(Decimal("5000")))],
        date(2024, 1, 1), Decimal("1000000"), Decimal("100"), Decimal("0"), date(2025, 12, 31),
    )
    total_cash = sum((cash.total for cash in _flows(Decimal("5000"))), Decimal(0))
    assert sum(row.interest_income for row in result.rows) == total_cash - Decimal("1000000")


def test_projection_change_is_caught_up_on_its_effective_date() -> None:
    base = ProjectionVersion(date(2024, 1, 1), _flows(Decimal("5000")))
    revised = ProjectionVersion(date(2024, 7, 1), _flows(Decimal("6000")))
    result = pass_through_amortization(
        DEAL, DEAL_FACTORS, [base, revised],
        date(2024, 1, 1), Decimal("1000000"), Decimal("100"), Decimal("0"), date(2025, 12, 31),
    )
    rows = {row.on: row for row in result.rows}
    jump = rows[date(2024, 7, 1)].amortization - rows[date(2024, 6, 30)].amortization
    assert jump > Decimal("10000")
    assert len({row.eir_periodic for row in result.rows}) == 1


def test_catch_up_equals_present_value_difference_at_old_rate() -> None:
    base_flows = _flows(Decimal("5000"))
    revised_flows = _flows(Decimal("6000"))
    result = pass_through_amortization(
        DEAL, DEAL_FACTORS,
        [ProjectionVersion(date(2024, 1, 1), base_flows), ProjectionVersion(date(2024, 7, 1), revised_flows)],
        date(2024, 1, 1), Decimal("1000000"), Decimal("100"), Decimal("0"), date(2025, 12, 31),
    )
    rate = result.eir_periodic
    on = date(2024, 7, 1)

    day_count = get_day_count("30E/360")
    accrual_period = AccrualPeriod(on, date(2025, 7, 1), 12)

    def discounted(flows):
        return [
            (cash.total, day_count.year_fraction(on, cash.pay_date, accrual_period) * 12)
            for cash in flows
            if cash.pay_date > on
        ]

    catch_up = present_value(discounted(revised_flows), rate) - present_value(discounted(base_flows), rate)
    rows = {row.on: row for row in result.rows}
    normal_day = rows[date(2024, 6, 30)].amortization
    assert abs(rows[on].amortization - normal_day - catch_up) < Decimal("1")
