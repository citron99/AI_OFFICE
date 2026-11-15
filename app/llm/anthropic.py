import re

from anthropic import AsyncAnthropic
from anthropic.types import TextBlock, ToolUseBlock
from pydantic import ValidationError

from app.core.exceptions import ModelOutputInvalidError
from app.llm.base import LLMProvider, StructuredModel
from app.llm.telemetry import record_usage

TOOL_NAME = "structured_output"
_FENCED_JSON = re.compile(r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL)


def _json_payload(text: str) -> str:
    """Claude often wraps JSON in a markdown fence despite instructions."""
    match = _FENCED_JSON.match(text)
    return match.group("body") if match else text


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
        # Tool use binds the model to the JSON schema server-side. The old
        # "Return JSON only" prompt let markdown fences leak into validation.
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": "Return the structured result for this step.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )
        record_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens,
            cache_write_tokens=response.usage.cache_creation_input_tokens,
        )
        tool_block = next(
            (
                block
                for block in response.content
                if isinstance(block, ToolUseBlock) and block.name == TOOL_NAME
            ),
            None,
        )
        try:
            if tool_block is not None:
                return response_model.model_validate(tool_block.input)
            text = "".join(block.text for block in response.content if isinstance(block, TextBlock))
            return response_model.model_validate_json(_json_payload(text))
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
