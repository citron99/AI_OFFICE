from typing import Any

from pydantic import BaseModel

from app.llm.base import LLMProvider, StructuredModel


class MockLLMProvider(LLMProvider):
    def __init__(self, response: dict[str, Any] | BaseModel | None = None) -> None:
        self.response = response

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        del system_prompt, user_prompt
        if isinstance(self.response, BaseModel):
            return response_model.model_validate(self.response.model_dump())
        if isinstance(self.response, dict):
            return response_model.model_validate(self.response)
        return response_model.model_validate({})

    async def healthcheck(self) -> bool:
        return True
