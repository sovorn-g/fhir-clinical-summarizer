"""LLM client configuration behavior."""

from __future__ import annotations

import json

from pydantic import BaseModel

from clinical_core.llm.client import LLMClient


class TinyPayload(BaseModel):
    ok: bool


def test_client_passes_generic_api_key_to_litellm():
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [{"message": {"content": json.dumps({"ok": True})}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    client = LLMClient(
        model="openai/test-model",
        api_key="test-key",
        raw_completion=fake_completion,
    )

    result = client.complete("system", "user", TinyPayload)

    assert result.ok is True
    assert captured["api_key"] == "test-key"
    assert "JSON Schema" in captured["messages"][0]["content"]
    assert '"ok"' in captured["messages"][0]["content"]
