"""Tariff catalog and the extended LLM provider contract (TZ 9.4, 12.3)."""

from decimal import Decimal

import pytest

from app.config import Settings
from app.llm.base import ProviderCapabilities
from app.llm.factory import create_llm_provider
from app.llm.tariffs import (
    CATALOG_VERSION,
    TariffError,
    estimate_cost,
    tariff_for,
)


def test_tariff_catalog_is_versioned_and_priced() -> None:
    assert CATALOG_VERSION == "tariffs-2026-09-v1"
    input_price, output_price = tariff_for("claude-sonnet-4-5")
    assert input_price < output_price  # output tokens cost more


def test_estimate_cost_is_deterministic_decimal_math() -> None:
    cost = estimate_cost(model_id="claude-sonnet-4-5", input_tokens=1000, output_tokens=500)
    expected = Decimal("2.50") + Decimal("12.50") * Decimal("0.5")
    assert cost == expected.quantize(Decimal("0.0001"))
    assert estimate_cost(model_id="mock", input_tokens=10**9, output_tokens=10**9) == 0


def test_unknown_model_refuses_a_zero_cost() -> None:
    with pytest.raises(TariffError, match="refusing to report a zero cost"):
        estimate_cost(model_id="unknown-model", input_tokens=1, output_tokens=1)


def test_provider_exposes_capabilities_and_cost_estimate() -> None:
    settings = Settings(app_env="test", llm_provider="mock")
    provider = create_llm_provider(settings)
    capabilities = provider.capabilities()
    assert isinstance(capabilities, ProviderCapabilities)
    assert capabilities.structured_output is True
    cost = provider.estimate_cost(input_tokens=1000, output_tokens=0)
    assert cost == 0  # the mock route is free by the tariff catalog


async def test_stream_is_declared_unsupported_by_default() -> None:
    settings = Settings(app_env="test", llm_provider="mock")
    provider = create_llm_provider(settings)
    with pytest.raises(NotImplementedError, match="streaming"):
        async for _ in provider.stream(system_prompt="s", user_prompt="u"):
            pass
