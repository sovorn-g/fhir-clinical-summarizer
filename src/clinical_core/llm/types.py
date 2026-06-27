"""LLM result / usage types (CONTRACTS §7)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class LLMResult(BaseModel, Generic[BaseModelT]):
    parsed: BaseModelT
    usage: Usage = Usage()
    raw_model: str = ""
