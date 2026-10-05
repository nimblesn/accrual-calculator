from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from accrual.schedule.coupon_schedule import CouponPeriod, StubType, generate_coupon_schedule


@dataclass(frozen=True)
class FixedRateBond:
    security_id: str
    currency: str
    issue_date: date
    dated_date: date
    maturity_date: date
    first_coupon_date: date | None
    coupon_rate: Decimal
    coupon_freq: int
    day_count_code: str
    end_of_month: bool
    redemption_price: Decimal
    last_stub: StubType = StubType.SHORT

    def __post_init__(self) -> None:
        if not isinstance(self.coupon_rate, Decimal):
            raise TypeError("coupon_rate must be Decimal")
        if not self.coupon_rate.is_finite() or self.coupon_rate < 0:
            raise ValueError(f"coupon_rate must be finite and non-negative: {self.coupon_rate}")
        if self.coupon_freq == 0 and self.coupon_rate != 0:
            raise ValueError("zero coupon bond must have coupon_rate 0")
        if not isinstance(self.redemption_price, Decimal) or not self.redemption_price.is_finite():
            raise ValueError("redemption_price must be a finite Decimal")

    def schedule(self) -> list[CouponPeriod]:
        return generate_coupon_schedule(
            issue_date=self.issue_date,
            dated_date=self.dated_date,
            maturity_date=self.maturity_date,
            first_coupon_date=self.first_coupon_date,
            coupon_freq=self.coupon_freq,
            end_of_month=self.end_of_month,
            last_stub=self.last_stub,
        )
