from decimal import ROUND_HALF_UP, Decimal, localcontext

_DECIMAL_PLACES_BY_CURRENCY: dict[str, int] = {"JPY": 0}
_DEFAULT_DECIMAL_PLACES = 2
_WORKING_PRECISION = 34


class RoundingPolicy:
    @staticmethod
    def decimal_places(currency: str) -> int:
        return _DECIMAL_PLACES_BY_CURRENCY.get(currency, _DEFAULT_DECIMAL_PLACES)

    @classmethod
    def round_amount(cls, amount: Decimal, currency: str) -> Decimal:
        exponent = Decimal(1).scaleb(-cls.decimal_places(currency))
        with localcontext() as ctx:
            ctx.prec = _WORKING_PRECISION
            return amount.quantize(exponent, rounding=ROUND_HALF_UP)
