from datetime import date
from decimal import Decimal

from accrual.accrual.tips import (
    interpolated_ref_cpi,
    index_ratio,
    inflation_compensation_on,
    maturity_redemption,
    tips_accrued_on,
)
from accrual.models.bond import TipsBond

# Terms mirror samples/security_master.csv SAMPLE0007.
SAMPLE0007 = TipsBond(
    security_id="SAMPLE0007",
    currency="USD",
    issue_date=date(2024, 1, 15),
    dated_date=date(2024, 1, 15),
    maturity_date=date(2034, 1, 15),
    first_coupon_date=date(2024, 7, 15),
    real_coupon_rate=Decimal("0.0125"),
    coupon_freq=2,
    day_count_code="ACT/TSY",
    end_of_month=False,
    base_ref_cpi=Decimal("307.39100"),
    deflation_floor=True,
)

BASE = Decimal("307.39100")


def flat(value: Decimal):
    return lambda _on: value


def test_index_ratio_rounds_to_five_places() -> None:
    assert index_ratio(BASE, BASE) == Decimal("1.00000")
    assert index_ratio(Decimal("338.13010"), BASE) == Decimal("1.10000")


def test_accrual_at_unit_index_ratio_uses_real_coupon() -> None:
    accrued = tips_accrued_on(SAMPLE0007, Decimal("1000000"), flat(BASE), date(2024, 3, 15))
    assert accrued == Decimal("2060.44")


def test_accrual_scales_with_index_ratio() -> None:
    doubled = tips_accrued_on(SAMPLE0007, Decimal("1000000"), flat(BASE * 2), date(2024, 3, 15))
    assert doubled == Decimal("4120.88")


def test_inflation_compensation_is_par_times_ratio_change() -> None:
    ref = lambda on: BASE if on == date(2024, 1, 15) else BASE * Decimal("1.05")
    assert inflation_compensation_on(
        SAMPLE0007, Decimal("1000000"), ref, date(2024, 1, 15), date(2024, 3, 15)
    ) == Decimal("50000.00")


def test_deflation_floor_keeps_par_at_maturity() -> None:
    assert maturity_redemption(SAMPLE0007, Decimal("1000000"), flat(BASE * Decimal("0.9"))) == Decimal("1000000.00")
    assert maturity_redemption(SAMPLE0007, Decimal("1000000"), flat(BASE * Decimal("1.1"))) == Decimal("1100000.00")


def test_without_floor_deflation_reduces_redemption() -> None:
    no_floor = TipsBond(**{**SAMPLE0007.__dict__, "deflation_floor": False})
    assert maturity_redemption(no_floor, Decimal("1000000"), flat(BASE * Decimal("0.9"))) == Decimal("900000.00")


CPI = {
    (2023, 10): Decimal("307.671"),
    (2023, 11): Decimal("307.051"),
    (2023, 12): Decimal("306.746"),
    (2024, 1): Decimal("308.417"),
    (2024, 2): Decimal("310.326"),
}


def test_ref_cpi_on_first_of_month_is_cpi_three_months_earlier() -> None:
    assert interpolated_ref_cpi(CPI, date(2024, 2, 1)) == Decimal("307.051")


def test_ref_cpi_mid_month_interpolates_linearly_over_days() -> None:
    assert interpolated_ref_cpi(CPI, date(2024, 1, 15)) == Decimal("307.391")
    assert interpolated_ref_cpi(CPI, date(2024, 1, 15)) == BASE


def test_ref_cpi_missing_month_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        interpolated_ref_cpi({}, date(2024, 1, 15))


def test_ref_cpi_is_rounded_half_up_to_five_places() -> None:
    cpi = {
        (2023, 11): Decimal("307.051"),
        (2023, 12): Decimal("306.746"),
        (2024, 1): Decimal("308.417"),
        (2024, 2): Decimal("310.326"),
    }
    assert interpolated_ref_cpi(cpi, date(2024, 2, 10)) == Decimal("306.95634")
