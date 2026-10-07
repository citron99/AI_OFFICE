from anthropic import AsyncAnthropic
from pydantic import ValidationError

from app.core.exceptions import ModelOutputInvalidError
from app.llm.base import LLMProvider, StructuredModel
from app.llm.telemetry import record_usage


class AnthropicProvider(LLMProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModel],
    ) -> StructuredModel:
        schema = response_model.model_json_schema()
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{user_prompt}\n\nReturn JSON only. "
                        f"The JSON must satisfy this schema:\n{schema}"
                    ),
                }
            ],
        )
        record_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens,
            cache_write_tokens=response.usage.cache_creation_input_tokens,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        try:
            return response_model.model_validate_json(text)
        except ValidationError as exc:
            raise ModelOutputInvalidError("LLM returned invalid structured output") from exc

    async def healthcheck(self) -> bool:
        try:
            await self.client.models.list(limit=1)
        except Exception:
            return False
        return True

    async def aclose(self) -> None:
        await self.client.close()
