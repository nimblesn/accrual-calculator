import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from accrual.rounding import RoundingPolicy

_DECIMAL = re.compile(r"-?\d+(\.\d+)?")
_INTEGER = re.compile(r"-?\d+")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MONTH = re.compile(r"\d{4}-\d{2}")
_CURRENCY = re.compile(r"[A-Z]{3}")


@dataclass(frozen=True)
class ValidationError:
    file: str
    row: int | None
    field: str | None
    message: str

    def __str__(self) -> str:
        location = self.file if self.row is None else f"{self.file}:{self.row}"
        field = f" [{self.field}]" if self.field else ""
        return f"{location}{field} {self.message}"


class ValidationFailed(Exception):
    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        super().__init__(f"{len(errors)} validation error(s)")


class Table:
    def __init__(self, directory: Path, name: str, required: tuple[str, ...], errors: list[ValidationError]) -> None:
        self.name = name
        self.rows: list[tuple[int, dict[str, str]]] = []
        path = directory / name
        if not path.exists():
            errors.append(ValidationError(name, None, None, "file is missing"))
            return
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = reader.fieldnames or []
            missing = [column for column in required if column not in header]
            if missing:
                errors.append(ValidationError(name, None, None, f"missing columns: {', '.join(missing)}"))
                return
            self.rows = [(line, dict(row)) for line, row in enumerate(reader, start=2)]


class RowReader:
    def __init__(self, file: str, row: int, values: dict[str, str], errors: list[ValidationError]) -> None:
        self._file = file
        self._row = row
        self._values = values
        self._errors = errors
        self.ok = True

    def _fail(self, field: str, message: str) -> None:
        self.ok = False
        self._errors.append(ValidationError(self._file, self._row, field, message))

    def _raw(self, field: str, required: bool) -> str | None:
        value = (self._values.get(field) or "").strip()
        if value == "":
            if required:
                self._fail(field, "required value is empty")
            return None
        return value

    def text(self, field: str, required: bool = True) -> str | None:
        return self._raw(field, required)

    def enum(self, field: str, allowed: tuple[str, ...], required: bool = True) -> str | None:
        value = self._raw(field, required)
        if value is None:
            return None
        if value not in allowed:
            self._fail(field, f"must be one of {', '.join(allowed)}: {value!r}")
            return None
        return value

    def yes_no(self, field: str, required: bool = True) -> bool | None:
        value = self._raw(field, required)
        if value is None:
            return None
        if value not in ("Y", "N"):
            self._fail(field, f"must be Y or N: {value!r}")
            return None
        return value == "Y"

    def decimal(self, field: str, required: bool = True, percent: bool = False) -> Decimal | None:
        value = self._raw(field, required)
        if value is None:
            return None
        if not _DECIMAL.fullmatch(value):
            self._fail(field, f"not a plain decimal (no exponent or separators): {value!r}")
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            self._fail(field, f"not a decimal: {value!r}")
            return None
        return number / 100 if percent else number

    def integer(self, field: str, required: bool = True) -> int | None:
        value = self._raw(field, required)
        if value is None:
            return None
        if not _INTEGER.fullmatch(value):
            self._fail(field, f"not an integer: {value!r}")
            return None
        return int(value)

    def date(self, field: str, required: bool = True) -> date | None:
        value = self._raw(field, required)
        if value is None:
            return None
        if not _DATE.fullmatch(value):
            self._fail(field, f"date must be YYYY-MM-DD: {value!r}")
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            self._fail(field, f"invalid date: {value!r}")
            return None

    def month(self, field: str) -> tuple[int, int] | None:
        value = self._raw(field, True)
        if value is None:
            return None
        if not _MONTH.fullmatch(value):
            self._fail(field, f"month must be YYYY-MM: {value!r}")
            return None
        year, month = int(value[:4]), int(value[5:])
        if not 1 <= month <= 12:
            self._fail(field, f"invalid month: {value!r}")
            return None
        return year, month

    def currency(self, field: str) -> str | None:
        value = self._raw(field, True)
        if value is None:
            return None
        if not _CURRENCY.fullmatch(value):
            self._fail(field, f"currency must be an uppercase ISO 4217 code: {value!r}")
            return None
        return value

    def amount(self, field: str, currency: str, required: bool = True) -> Decimal | None:
        number = self.decimal(field, required)
        if number is None:
            return None
        if number != number.quantize(Decimal(1).scaleb(-RoundingPolicy.decimal_places(currency))):
            self._fail(field, f"more decimal places than {currency} allows")
            return None
        return number

    def fail(self, field: str | None, message: str) -> None:
        self.ok = False
        self._errors.append(ValidationError(self._file, self._row, field, message))
