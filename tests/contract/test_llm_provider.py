import asyncio

from pydantic import BaseModel

from app.llm.base import LLMProvider
from app.llm.mock import MockLLMProvider


class ExampleOutput(BaseModel):
    message: str


async def llm_provider_contract(provider: LLMProvider) -> None:
    assert await provider.healthcheck()
    result = await provider.generate_structured(
        system_prompt="Return structured data",
        user_prompt="Hello",
        response_model=ExampleOutput,
    )
    assert isinstance(result, ExampleOutput)


def test_mock_llm_provider_contract() -> None:
    asyncio.run(llm_provider_contract(MockLLMProvider({"message": "ok"})))
