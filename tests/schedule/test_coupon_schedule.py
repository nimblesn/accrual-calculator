from datetime import date

import pytest

from accrual.schedule.coupon_schedule import (
    CouponPeriod,
    StubType,
    find_period,
    generate_coupon_schedule,
)


def boundaries(periods: list[CouponPeriod]) -> list[tuple[date, date]]:
    return [(p.start, p.end) for p in periods]


def test_semiannual_with_explicit_first_coupon() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2024, 1, 15),
        dated_date=date(2024, 1, 15),
        maturity_date=date(2029, 1, 15),
        first_coupon_date=date(2024, 7, 15),
        coupon_freq=2,
        end_of_month=False,
    )
    assert len(periods) == 10
    assert periods[0] == CouponPeriod(date(2024, 1, 15), date(2024, 7, 15), date(2024, 7, 15))
    assert periods[1] == CouponPeriod(date(2024, 7, 15), date(2025, 1, 15), date(2025, 1, 15))
    assert periods[-1] == CouponPeriod(date(2028, 7, 15), date(2029, 1, 15), date(2029, 1, 15))


def test_short_last_stub_keeps_final_short_period() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2024, 1, 15),
        dated_date=date(2024, 1, 15),
        maturity_date=date(2024, 12, 15),
        first_coupon_date=None,
        coupon_freq=4,
        end_of_month=False,
    )
    assert boundaries(periods) == [
        (date(2024, 1, 15), date(2024, 4, 15)),
        (date(2024, 4, 15), date(2024, 7, 15)),
        (date(2024, 7, 15), date(2024, 10, 15)),
        (date(2024, 10, 15), date(2024, 12, 15)),
    ]


def test_long_last_stub_merges_into_previous_period() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2024, 1, 15),
        dated_date=date(2024, 1, 15),
        maturity_date=date(2024, 12, 15),
        first_coupon_date=None,
        coupon_freq=4,
        end_of_month=False,
        last_stub=StubType.LONG,
    )
    assert boundaries(periods) == [
        (date(2024, 1, 15), date(2024, 4, 15)),
        (date(2024, 4, 15), date(2024, 7, 15)),
        (date(2024, 7, 15), date(2024, 12, 15)),
    ]


def test_aligned_maturity_has_no_stub_regardless_of_flag() -> None:
    kwargs = dict(
        issue_date=date(2024, 1, 15),
        dated_date=date(2024, 1, 15),
        maturity_date=date(2024, 10, 15),
        first_coupon_date=None,
        coupon_freq=4,
        end_of_month=False,
    )
    short = generate_coupon_schedule(**kwargs, last_stub=StubType.SHORT)
    long = generate_coupon_schedule(**kwargs, last_stub=StubType.LONG)
    assert short == long
    assert len(short) == 3


def test_end_of_month_flag_moves_to_month_end() -> None:
    kwargs = dict(
        issue_date=date(2023, 8, 31),
        dated_date=date(2023, 8, 31),
        maturity_date=date(2025, 2, 28),
        first_coupon_date=date(2024, 2, 29),
        coupon_freq=2,
    )
    with_eom = generate_coupon_schedule(**kwargs, end_of_month=True)
    without_eom = generate_coupon_schedule(**kwargs, end_of_month=False)
    assert [p.end for p in with_eom] == [date(2024, 2, 29), date(2024, 8, 31), date(2025, 2, 28)]
    assert [p.end for p in without_eom] == [date(2024, 2, 29), date(2024, 8, 29), date(2025, 2, 28)]


def test_february_maturity_with_eom_uses_month_end() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2023, 2, 28),
        dated_date=date(2023, 2, 28),
        maturity_date=date(2024, 2, 29),
        first_coupon_date=date(2023, 8, 31),
        coupon_freq=2,
        end_of_month=True,
    )
    assert boundaries(periods) == [
        (date(2023, 2, 28), date(2023, 8, 31)),
        (date(2023, 8, 31), date(2024, 2, 29)),
    ]


def test_first_coupon_equal_to_dated_date_has_no_initial_stub() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2024, 1, 15),
        dated_date=date(2024, 1, 15),
        maturity_date=date(2025, 1, 15),
        first_coupon_date=date(2024, 1, 15),
        coupon_freq=2,
        end_of_month=False,
    )
    assert boundaries(periods) == [
        (date(2024, 1, 15), date(2024, 7, 15)),
        (date(2024, 7, 15), date(2025, 1, 15)),
    ]


def test_zero_coupon_is_single_period_paid_at_maturity() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2024, 3, 1),
        dated_date=date(2024, 3, 1),
        maturity_date=date(2027, 3, 1),
        first_coupon_date=None,
        coupon_freq=0,
        end_of_month=False,
    )
    assert periods == [CouponPeriod(date(2024, 3, 1), date(2027, 3, 1), date(2027, 3, 1))]


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(issue_date=date(2024, 2, 1), dated_date=date(2024, 1, 1), maturity_date=date(2025, 1, 1)),
        dict(issue_date=date(2024, 1, 1), dated_date=date(2025, 1, 1), maturity_date=date(2025, 1, 1)),
        dict(
            issue_date=date(2024, 1, 1),
            dated_date=date(2024, 1, 1),
            maturity_date=date(2025, 1, 1),
            first_coupon_date=date(2025, 6, 1),
        ),
    ],
)
def test_invalid_dates_raise(kwargs) -> None:
    with pytest.raises(ValueError):
        generate_coupon_schedule(
            **{"first_coupon_date": None, **kwargs}, coupon_freq=2, end_of_month=False
        )


def test_unsupported_frequency_raises() -> None:
    with pytest.raises(ValueError):
        generate_coupon_schedule(
            issue_date=date(2024, 1, 1),
            dated_date=date(2024, 1, 1),
            maturity_date=date(2025, 1, 1),
            first_coupon_date=None,
            coupon_freq=3,
            end_of_month=False,
        )


def test_zero_coupon_with_first_coupon_raises() -> None:
    with pytest.raises(ValueError):
        generate_coupon_schedule(
            issue_date=date(2024, 1, 1),
            dated_date=date(2024, 1, 1),
            maturity_date=date(2025, 1, 1),
            first_coupon_date=date(2024, 7, 1),
            coupon_freq=0,
            end_of_month=False,
        )


def test_find_period_on_coupon_date_returns_next_period() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2024, 1, 15),
        dated_date=date(2024, 1, 15),
        maturity_date=date(2025, 1, 15),
        first_coupon_date=date(2024, 7, 15),
        coupon_freq=2,
        end_of_month=False,
    )
    assert find_period(periods, date(2024, 7, 15)).start == date(2024, 7, 15)
    assert find_period(periods, date(2024, 3, 1)).start == date(2024, 1, 15)


def test_find_period_outside_schedule_raises() -> None:
    periods = generate_coupon_schedule(
        issue_date=date(2024, 1, 15),
        dated_date=date(2024, 1, 15),
        maturity_date=date(2025, 1, 15),
        first_coupon_date=date(2024, 7, 15),
        coupon_freq=2,
        end_of_month=False,
    )
    with pytest.raises(ValueError):
        find_period(periods, date(2023, 12, 31))
    with pytest.raises(ValueError):
        find_period(periods, date(2025, 1, 15))
