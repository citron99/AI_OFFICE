from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, TypeVar

from pydantic import BaseModel

from app.llm.tariffs import estimate_cost

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class ProviderCapabilities(BaseModel):
    """What a route supports (TZ 9.4): route choice is capability-driven."""

    streaming: bool = False
    structured_output: bool = True
    function_calling: bool = False
    max_input_tokens: int = 100_000


class LLMProvider(ABC):
    # The route's model id, set by the factory; cost estimates come from the
    # versioned tariff catalog, never hardcoded.
    model_id: str = "claude-sonnet-4-5"

    async def aclose(self) -> None:
        """Release provider resources, if any."""
        return None

    @abstractmethod
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        raise NotImplementedError

    @abstractmethod
    async def healthcheck(self) -> bool:
        raise NotImplementedError

    async def stream(self, *, system_prompt: str, user_prompt: str) -> AsyncIterator[str]:
        """Token stream for interactive surfaces; default: not supported."""
        raise NotImplementedError("streaming is not supported by this provider")
        yield ""  # pragma: no cover - keeps this an async generator

    def estimate_cost(self, *, input_tokens: int, output_tokens: int) -> Any:
        """Deterministic cost from the versioned tariff catalog (TZ 12.3)."""
        return estimate_cost(
            model_id=self.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()
