"""Per-call metrics without prompts, secrets or fabricated token estimates."""

from contextvars import ContextVar
from time import perf_counter
from typing import Literal

from pydantic import BaseModel

from app.llm.base import LLMProvider, StructuredModel


class ModelCallInfo(BaseModel):
    schema_name: str
    status: Literal["completed", "failed", "cancelled"]
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    cost: str | None = None


_usage: ContextVar[dict[str, int] | None] = ContextVar("model_call_usage", default=None)


def record_usage(**counts: int | None) -> None:
    current = _usage.get()
    if current is not None:
        current.update({key: value for key, value in counts.items() if value is not None})


async def tracked_generate(
    provider: LLMProvider,
    *,
    records: list[ModelCallInfo],
    system_prompt: str,
    user_prompt: str,
    response_model: type[StructuredModel],
) -> StructuredModel:
    usage: dict[str, int] = {}
    token = _usage.set(usage)
    started = perf_counter()
    status: Literal["completed", "failed", "cancelled"] = "completed"
    try:
        return await provider.generate_structured(
            system_prompt=system_prompt, user_prompt=user_prompt, response_model=response_model
        )
    except Exception:
        status = "failed"
        raise
    except BaseException:
        status = "cancelled"
        raise
    finally:
        records.append(
            ModelCallInfo(
                schema_name=response_model.__name__,
                status=status,
                latency_ms=round((perf_counter() - started) * 1000),
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
                cache_read_tokens=usage.get("cache_read_tokens"),
                cache_write_tokens=usage.get("cache_write_tokens"),
            )
        )
        _usage.reset(token)
