from datetime import date
from decimal import Decimal

from accrual.accrual.floating import Fixing
from accrual.amortization.effective_interest import fixed_rate_amortization, floating_amortization
from accrual.models.bond import FixedRateBond
from accrual.models.bond import FloatingRateBond

SAMPLE0004 = FloatingRateBond(
    security_id="SAMPLE0004",
    currency="USD",
    issue_date=date(2024, 1, 10),
    dated_date=date(2024, 1, 10),
    maturity_date=date(2026, 1, 10),
    first_coupon_date=None,
    coupon_freq=4,
    day_count_code="ACT/360",
    end_of_month=False,
    redemption_price=Decimal("100"),
    index_name="SOFR",
    spread=Decimal("0.00350"),
    multiplier=Decimal("1"),
)

FIXINGS = [
    Fixing("SOFR", date(2024, 1, 10), Decimal("0.05300")),
    Fixing("SOFR", date(2024, 4, 10), Decimal("0.05250")),
    Fixing("SOFR", date(2024, 7, 10), Decimal("0.05100")),
]


def test_par_purchase_amortization_sums_to_zero_and_redeems_at_par() -> None:
    result = floating_amortization(
        SAMPLE0004, Decimal("1000000"), FIXINGS, date(2024, 1, 10), Decimal("100"), Decimal("0"), date(2026, 1, 10)
    )
    assert sum(row.amortization for row in result.rows) == Decimal("0")
    assert result.rows[-1].amortized_cost == Decimal("1000000.00")


def test_discount_purchase_amortization_sums_to_gain() -> None:
    result = floating_amortization(
        SAMPLE0004, Decimal("2000000"), FIXINGS, date(2024, 4, 12), Decimal("99"), Decimal("0"), date(2026, 1, 10)
    )
    assert sum(row.amortization for row in result.rows) == Decimal("20000.00")


def test_eir_is_recomputed_at_each_reset() -> None:
    result = floating_amortization(
        SAMPLE0004, Decimal("1000000"), FIXINGS, date(2024, 1, 10), Decimal("99"), Decimal("0"), date(2024, 10, 10)
    )
    first_period = {row.eir_periodic for row in result.rows if row.on <= date(2024, 4, 10)}
    second_period = {row.eir_periodic for row in result.rows if date(2024, 4, 10) < row.on <= date(2024, 7, 10)}
    assert len(first_period) == 1 and len(second_period) == 1
    assert first_period != second_period


def test_constant_index_keeps_eir_constant_across_resets() -> None:
    constant = [
        Fixing("SOFR", date(2024, 1, 10), Decimal("0.05000")),
        Fixing("SOFR", date(2024, 4, 10), Decimal("0.05000")),
        Fixing("SOFR", date(2024, 7, 10), Decimal("0.05000")),
    ]
    bond = FloatingRateBond(**{**SAMPLE0004.__dict__, "spread": Decimal("0")})
    result = floating_amortization(
        bond, Decimal("1000000"), constant, date(2024, 1, 10), Decimal("100"), Decimal("0"), date(2024, 10, 10)
    )
    rates = {row.eir_periodic for row in result.rows}
    assert max(rates) - min(rates) < Decimal("1E-10")
    fixed = FixedRateBond(
        security_id="FIXED_EQUIV",
        currency="USD",
        issue_date=date(2024, 1, 10),
        dated_date=date(2024, 1, 10),
        maturity_date=date(2026, 1, 10),
        first_coupon_date=None,
        coupon_rate=Decimal("0.05000"),
        coupon_freq=4,
        day_count_code="ACT/360",
        end_of_month=False,
        redemption_price=Decimal("100"),
    )
    fixed_result = fixed_rate_amortization(
        fixed, Decimal("1000000"), date(2024, 1, 10), Decimal("100"), Decimal("0"), date(2024, 10, 10)
    )
    assert abs(result.eir_periodic - fixed_result.eir_periodic) < Decimal("1E-10")
