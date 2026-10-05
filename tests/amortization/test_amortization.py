from datetime import date
from decimal import Decimal

import pytest

from accrual.amortization.eir_solver import solve_periodic_eir
from accrual.amortization.effective_interest import fixed_rate_amortization
from accrual.amortization.straight_line import zero_coupon_amortization
from accrual.models.bond import FixedRateBond

PAR_BOND = FixedRateBond(
    security_id="PAR",
    currency="USD",
    issue_date=date(2024, 1, 15),
    dated_date=date(2024, 1, 15),
    maturity_date=date(2026, 1, 15),
    first_coupon_date=date(2024, 7, 15),
    coupon_rate=Decimal("0.0425"),
    coupon_freq=2,
    day_count_code="30E/360",
    end_of_month=False,
    redemption_price=Decimal("100"),
)

SAMPLE0001 = FixedRateBond(
    security_id="SAMPLE0001",
    currency="USD",
    issue_date=date(2024, 1, 15),
    dated_date=date(2024, 1, 15),
    maturity_date=date(2029, 1, 15),
    first_coupon_date=date(2024, 7, 15),
    coupon_rate=Decimal("0.0425"),
    coupon_freq=2,
    day_count_code="30E/360",
    end_of_month=False,
    redemption_price=Decimal("100"),
)

ZERO_JPY = FixedRateBond(
    security_id="SAMPLE0002",
    currency="JPY",
    issue_date=date(2024, 3, 1),
    dated_date=date(2024, 3, 1),
    maturity_date=date(2027, 3, 1),
    first_coupon_date=None,
    coupon_rate=Decimal("0"),
    coupon_freq=0,
    day_count_code="ACT/365",
    end_of_month=False,
    redemption_price=Decimal("100"),
)


def quantized(value: Decimal, places: int = 10) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places))


def test_solver_single_cash_flow() -> None:
    rate = solve_periodic_eir([(Decimal("105"), Decimal("1"))], Decimal("100"))
    assert quantized(rate) == Decimal("0.05")


def test_solver_two_cash_flows() -> None:
    flows = [(Decimal("5"), Decimal("1")), (Decimal("105"), Decimal("2"))]
    assert quantized(solve_periodic_eir(flows, Decimal("100"))) == Decimal("0.05")


def test_solver_rejects_unbracketed_target() -> None:
    with pytest.raises(ValueError):
        solve_periodic_eir([(Decimal("1"), Decimal("1"))], Decimal("1E30"))


def test_par_purchase_eir_equals_coupon_rate_per_period() -> None:
    result = fixed_rate_amortization(
        PAR_BOND, Decimal("1000000"), date(2024, 1, 15), Decimal("100"), Decimal("0"), date(2026, 1, 15)
    )
    assert quantized(result.eir_periodic) == Decimal("0.02125")
    assert quantized(result.eir_annual, 8) == quantized((1 + Decimal("0.02125")) ** 2 - 1, 8)


def test_par_purchase_has_no_amortization_and_redeems_at_par() -> None:
    result = fixed_rate_amortization(
        PAR_BOND, Decimal("1000000"), date(2024, 1, 15), Decimal("100"), Decimal("0"), date(2026, 1, 15)
    )
    assert sum(row.amortization for row in result.rows) == Decimal("0")
    first_period = [row for row in result.rows if row.on <= date(2024, 7, 15)]
    assert abs(sum(row.amortization for row in first_period)) <= Decimal("0.02")
    assert result.rows[-1].amortized_cost == Decimal("1000000.00")


def test_discount_purchase_amortization_sums_to_gain() -> None:
    result = fixed_rate_amortization(
        SAMPLE0001, Decimal("1000000"), date(2024, 2, 22), Decimal("98.750"), Decimal("0"), date(2029, 1, 15)
    )
    assert sum(row.amortization for row in result.rows) == Decimal("12500.00")
    assert result.rows[-1].amortized_cost == Decimal("1000000.00")
    assert result.eir_periodic > Decimal("0.02125")


def test_discount_purchase_matches_point_accrual_on_first_row() -> None:
    result = fixed_rate_amortization(
        SAMPLE0001, Decimal("1000000"), date(2024, 2, 22), Decimal("98.750"), Decimal("0"), date(2024, 3, 1)
    )
    assert result.rows[0].on == date(2024, 2, 23)
    assert result.rows[0].accrued_cum == Decimal("4486.11")


def test_coupon_date_row_resets_accrued_balance() -> None:
    result = fixed_rate_amortization(
        SAMPLE0001, Decimal("1000000"), date(2024, 2, 22), Decimal("98.750"), Decimal("0"), date(2024, 7, 15)
    )
    coupon_row = result.rows[-1]
    assert coupon_row.on == date(2024, 7, 15)
    assert coupon_row.accrued_cum == Decimal("0.00")


def test_fixed_rate_rejects_zero_coupon_bond() -> None:
    with pytest.raises(ValueError):
        fixed_rate_amortization(
            ZERO_JPY, Decimal("10000000"), date(2024, 3, 4), Decimal("98.5"), Decimal("0"), date(2027, 3, 1)
        )


def test_zero_coupon_straight_line_total_and_maturity_balance() -> None:
    result = zero_coupon_amortization(
        ZERO_JPY, Decimal("10000000"), date(2024, 3, 4), Decimal("98.5"), Decimal("0"), date(2027, 3, 1)
    )
    assert len(result.rows) == 1092
    assert sum(row.amortization for row in result.rows) == Decimal("150000")
    assert result.rows[-1].amortized_cost == Decimal("10000000")
    assert result.eir_periodic is None


def test_zero_coupon_daily_rounding_follows_cumulative_method() -> None:
    result = zero_coupon_amortization(
        ZERO_JPY, Decimal("10000000"), date(2024, 3, 4), Decimal("98.5"), Decimal("0"), date(2024, 3, 6)
    )
    assert [row.amortization for row in result.rows] == [Decimal("137"), Decimal("138")]
    assert result.rows[0].interest_income == result.rows[0].amortization
    assert result.rows[0].amortized_cost == Decimal("9850137")


def test_straight_line_rejects_coupon_bond() -> None:
    with pytest.raises(ValueError):
        zero_coupon_amortization(
            SAMPLE0001, Decimal("1000000"), date(2024, 2, 22), Decimal("98.75"), Decimal("0"), date(2024, 3, 1)
        )
