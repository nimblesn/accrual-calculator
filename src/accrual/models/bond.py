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


@dataclass(frozen=True)
class FloatingRateBond:
    security_id: str
    currency: str
    issue_date: date
    dated_date: date
    maturity_date: date
    first_coupon_date: date | None
    coupon_freq: int
    day_count_code: str
    end_of_month: bool
    redemption_price: Decimal
    index_name: str
    spread: Decimal
    multiplier: Decimal
    cap: Decimal | None = None
    floor: Decimal | None = None
    last_stub: StubType = StubType.SHORT

    def __post_init__(self) -> None:
        for name in ("spread", "multiplier", "redemption_price"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{name} must be a finite Decimal")
        if self.coupon_freq < 1:
            raise ValueError("floating rate bond must have a positive coupon frequency")
        if self.cap is not None and self.floor is not None and self.cap < self.floor:
            raise ValueError("cap must not be below floor")

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

    def coupon_rate(self, index_rate: Decimal) -> Decimal:
        rate = index_rate * self.multiplier + self.spread
        if self.floor is not None and rate < self.floor:
            rate = self.floor
        if self.cap is not None and rate > self.cap:
            rate = self.cap
        return rate


@dataclass(frozen=True)
class PassThroughBond:
    security_id: str
    bond_type: str
    currency: str
    issue_date: date
    dated_date: date
    maturity_date: date
    coupon_rate: Decimal
    coupon_freq: int
    day_count_code: str
    end_of_month: bool
    original_face: Decimal
    payment_delay_days: int = 0
    last_stub: StubType = StubType.SHORT

    def __post_init__(self) -> None:
        if self.bond_type not in ("MBS", "ABS"):
            raise ValueError(f"bond_type must be MBS or ABS: {self.bond_type}")
        if not self.coupon_rate.is_finite() or self.coupon_rate < 0:
            raise ValueError("coupon_rate must be finite and non-negative")
        if self.coupon_freq < 1:
            raise ValueError("pass-through bond must have a positive coupon frequency")
        if not self.original_face.is_finite() or self.original_face <= 0:
            raise ValueError("original_face must be positive")

    def schedule(self) -> list[CouponPeriod]:
        return generate_coupon_schedule(
            issue_date=self.issue_date,
            dated_date=self.dated_date,
            maturity_date=self.maturity_date,
            first_coupon_date=None,
            coupon_freq=self.coupon_freq,
            end_of_month=self.end_of_month,
            last_stub=self.last_stub,
        )
