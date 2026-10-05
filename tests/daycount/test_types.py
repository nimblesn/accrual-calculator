from datetime import date

import pytest

from accrual.daycount.base import UnsupportedDayCountError
from accrual.daycount.types import get_day_count


@pytest.mark.parametrize(
    "code",
    ["D30/360", "30E/360", "30P/360", "NL/365", "ACT/365", "ACT/360", "ACT/AFB", "ACT/TSY", "ACT/ACT", "ACT/366"],
)
def test_supported_codes_resolve(code: str) -> None:
    assert get_day_count(code) is not None


@pytest.mark.parametrize("code", ["C30/360", "Not support", "8", "9", "BOGUS", "", "act/365"])
def test_unsupported_codes_raise(code: str) -> None:
    with pytest.raises(UnsupportedDayCountError):
        get_day_count(code)


def test_30p_360_is_bond_basis_alias() -> None:
    start, end = date(2024, 2, 29), date(2024, 3, 31)
    assert get_day_count("30P/360").day_count(start, end) == get_day_count("D30/360").day_count(start, end)
    assert get_day_count("30P/360").day_count(start, end) == 32
