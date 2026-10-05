from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class AccrualPeriod:
    start: date
    end: date
    coupon_freq: int

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"period end must be after start: {self.start} -> {self.end}")
        if self.coupon_freq < 1:
            raise ValueError(f"coupon_freq must be positive: {self.coupon_freq}")


@dataclass(frozen=True)
class CashFlow:
    pay_date: date
    principal: Decimal
    interest: Decimal

    @property
    def total(self) -> Decimal:
        return self.principal + self.interest


@dataclass(frozen=True)
class ProjectionVersion:
    effective_date: date
    flows: tuple[CashFlow, ...]
