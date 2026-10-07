from app.config import Settings
from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        provider = MockLLMProvider()
        provider.model_id = "mock"
        return provider
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the anthropic provider")
    from app.llm.anthropic import AnthropicProvider

    return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.llm_model)
