from datetime import date
from decimal import Decimal

from accrual.accrual.tips import interpolated_ref_cpi, tips_accrued_on, tips_projections
from accrual.amortization.tips import tips_amortization
from accrual.models.bond import TipsBond

# Synthetic CPI for tests only: rises 0.3 index points per month.
CPI = {
    (y, m): Decimal("300") + Decimal("0.3") * ((y - 2023) * 12 + m - 1)
    for y in range(2023, 2027)
    for m in range(1, 13)
}


def ref(on: date) -> Decimal:
    return interpolated_ref_cpi(CPI, on)


BOND = TipsBond(
    security_id="TIPS_TEST",
    currency="USD",
    issue_date=date(2024, 1, 15),
    dated_date=date(2024, 1, 15),
    maturity_date=date(2025, 1, 15),
    first_coupon_date=date(2024, 7, 15),
    real_coupon_rate=Decimal("0.0125"),
    coupon_freq=2,
    day_count_code="ACT/TSY",
    end_of_month=False,
    base_ref_cpi=ref(date(2024, 1, 15)),
    deflation_floor=True,
)
PAR = Decimal("1000000")


def run(end: date = date(2024, 12, 31)):
    return tips_amortization(BOND, PAR, CPI, date(2024, 2, 20), Decimal("100"), Decimal("0"), end)


def test_one_projection_version_per_month_from_settlement_to_maturity() -> None:
    versions = tips_projections(BOND, PAR, ref, date(2024, 2, 20))
    assert [v.version for v in versions] == list(range(1, 13))
    assert versions[0].effective_date == date(2024, 2, 1)
    assert versions[-1].effective_date == date(2025, 1, 1)


def test_eir_is_unchanged_by_cpi_resets_under_catch_up() -> None:
    rates = {row.eir_periodic for row in run().rows}
    assert max(rates) - min(rates) < Decimal("1E-9")


def test_cpi_reset_is_caught_up_through_amortization_on_the_reset_date() -> None:
    rows = {row.on: row for row in run().rows}
    assert rows[date(2024, 3, 1)].amortization > Decimal("500")
    assert abs(rows[date(2024, 3, 2)].amortization) < Decimal("10")


def test_accrued_interest_is_index_linked_and_resets_on_coupon_date() -> None:
    rows = {row.on: row for row in run().rows}
    assert rows[date(2024, 3, 20)].accrued_cum == tips_accrued_on(BOND, PAR, ref, date(2024, 3, 20))
    assert rows[date(2024, 7, 15)].accrued_cum == Decimal("0.00")


def test_row_count_covers_each_day_in_the_range() -> None:
    assert len(run().rows) == (date(2024, 12, 31) - date(2024, 2, 20)).days
