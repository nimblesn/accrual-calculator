import re
from dataclasses import dataclass
from decimal import Decimal

from accrual.rounding import RoundingPolicy

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(f"amount must be Decimal, got {type(self.amount).__name__}")
        if not self.amount.is_finite():
            raise ValueError(f"amount must be finite: {self.amount}")
        if not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError(f"currency must be an uppercase ISO 4217 code: {self.currency!r}")

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def rounded(self) -> "Money":
        return Money(RoundingPolicy.round_amount(self.amount, self.currency), self.currency)

    def _require_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")
