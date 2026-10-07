"""Versioned tariff catalog: model prices are never hardcoded in logic (TZ 12.3)."""

from datetime import date
from decimal import Decimal

CATALOG_VERSION = "tariffs-2026-09-v1"
CATALOG_VALID_FROM = date(2026, 9, 1)

# RUB per 1K tokens.
_TARIFFS: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-4-5": (Decimal("2.50"), Decimal("12.50")),
    "mock": (Decimal("0"), Decimal("0")),
}


class TariffError(LookupError):
    pass


def tariff_for(model_id: str) -> tuple[Decimal, Decimal]:
    if model_id not in _TARIFFS:
        raise TariffError(
            f"Model {model_id} is not in tariff catalog {CATALOG_VERSION}; "
            "refusing to report a zero cost"
        )
    return _TARIFFS[model_id]


def estimate_cost(*, model_id: str, input_tokens: int, output_tokens: int) -> Decimal:
    input_price, output_price = tariff_for(model_id)
    cost = input_price * input_tokens / 1000 + output_price * output_tokens / 1000
    return cost.quantize(Decimal("0.0001"))
