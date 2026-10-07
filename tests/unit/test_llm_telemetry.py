import asyncio

import pytest
from pydantic import BaseModel

from app.llm.base import LLMProvider
from app.llm.telemetry import record_usage, tracked_generate


class Output(BaseModel):
    ok: bool


class Provider(LLMProvider):
    async def generate_structured(self, *, system_prompt, user_prompt, response_model):
        record_usage(input_tokens=int(user_prompt), output_tokens=2)
        await asyncio.sleep(0)
        if system_prompt == "fail":
            raise ValueError("sensitive content")
        return response_model(ok=True)

    async def healthcheck(self):
        return True


async def test_usage_isolated_between_concurrent_calls():
    async def call(count):
        records = []
        await tracked_generate(
            Provider(),
            records=records,
            system_prompt="ok",
            user_prompt=str(count),
            response_model=Output,
        )
        return records[0]

    first, second = await asyncio.gather(call(10), call(20))
    assert first.input_tokens == 10
    assert second.input_tokens == 20
    assert first.cost is None
    assert first.status == "completed"


async def test_failure_records_usage_but_not_sensitive_exception():
    records = []
    with pytest.raises(ValueError):
        await tracked_generate(
            Provider(),
            records=records,
            system_prompt="fail",
            user_prompt="12",
            response_model=Output,
        )
    assert records[0].status == "failed"
    assert records[0].input_tokens == 12
    assert "sensitive" not in records[0].model_dump_json()
