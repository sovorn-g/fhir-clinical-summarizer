"""Provider-agnostic LLM wrapper around LiteLLM (CONTRACTS §7).

One door to the model: ``complete(system, user, schema) -> BaseModel``. Configure provider +
model + key in ``.env`` (``LLM_MODEL`` and ``API_KEY``). Structured output is JSON-validated with
Pydantic so ``Summary`` / judge verdicts come back typed. Token + cost are logged per call and
exposed on ``Summary``.

Don't add a provider abstraction layer — LiteLLM *is* the abstraction.
"""

from __future__ import annotations

import json
import logging
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from clinical_core.config.settings import get_settings
from clinical_core.llm.types import LLMResult, Usage

log = logging.getLogger(__name__)

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)

_SYSTEM_JSON_SUFFIX = (
    "\n\nRespond with a single JSON object that conforms exactly to this JSON Schema:\n"
    "{schema}\n\nOutput ONLY the JSON object, no prose, no markdown fences."
)


class LLMClient(Generic[BaseModelT]):
    """Thin, testable LiteLLM wrapper.

    ``raw_completion`` may be injected for tests (a callable mimicking
    ``litellm.completion``). In production it is ``litellm.completion`` (imported lazily so the
    package imports without the SDK or a network round-trip).
    """

    def __init__(
        self,
        model: str | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        api_key: str | None = None,
        raw_completion=None,
    ) -> None:
        s = get_settings()
        self.model = model or s.llm_model
        self.temperature = temperature if temperature is not None else s.clinical_llm_temperature
        self.max_tokens = max_tokens or s.clinical_llm_max_tokens
        self.api_key = api_key if api_key is not None else s.api_key
        self._raw_completion = raw_completion  # if None, lazily import litellm on first call

    # -- public API -----------------------------------------------------------
    def complete(self, system: str, user: str, schema: type[BaseModelT]) -> BaseModelT:
        """Return a validated ``schema`` instance (CONTRACTS §7 signature)."""
        return self.complete_with_usage(system, user, schema).parsed

    def complete_with_usage(
        self, system: str, user: str, schema: type[BaseModelT]
    ) -> LLMResult[BaseModelT]:
        result = self._call(system, user, schema)
        log.info(
            "llm call model=%s in=%d out=%d cost=$%.4f",
            self.model,
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.cost_usd,
        )
        return result

    # -- internals ------------------------------------------------------------
    def _call(self, system: str, user: str, schema: type[BaseModelT]) -> LLMResult[BaseModelT]:
        completion = self._raw_completion or self._litellm_completion()
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {"role": "system", "content": system + _SYSTEM_JSON_SUFFIX.format(schema=schema_json)},
            {"role": "user", "content": user},
        ]
        request = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if self.api_key:
            request["api_key"] = self.api_key
        response = completion(**request)
        text = _extract_text(response)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMOutputError(
                f"non-JSON response from {self.model}: {exc}\n--- start ---\n{text[:800]}"
                f"\n--- end ---\n{text[-800:]}"
            ) from exc
        try:
            parsed = schema.model_validate(data)
        except ValidationError as exc:
            raise LLMOutputError(f"response failed {schema.__name__} validation: {exc}") from exc
        usage = _extract_usage(response, self.model)
        return LLMResult(parsed=parsed, usage=usage, raw_model=self.model)

    def _litellm_completion(self):
        import litellm  # local import: package imports without the SDK installed

        # LiteLLM is noisy; keep our own log line above its chatter.
        litellm.suppress_debug_info = True
        return litellm.completion


class LLMOutputError(RuntimeError):
    """Raised when the model output can't be parsed/validated into the schema."""


# --- response parsing helpers -------------------------------------------------
def _extract_text(response) -> str:
    try:
        return response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        # litellm ModelResponse objects support .choices too; fall back to attribute access
        try:
            return response.choices[0].message.content or ""  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise LLMOutputError(f"could not read completion content: {exc}") from exc


def _extract_usage(response, model: str) -> Usage:
    in_tok = out_tok = 0
    cost = 0.0
    try:
        u = response.get("usage") or getattr(response, "usage", None)
        if u is not None:
            in_tok = int(getattr(u, "prompt_tokens", u.get("prompt_tokens", 0)) or 0)
            out_tok = int(getattr(u, "completion_tokens", u.get("completion_tokens", 0)) or 0)
    except Exception:  # noqa: BLE001
        pass
    try:
        import litellm

        cost = float(litellm.completion_cost(completion_response=response) or 0.0)
    except Exception:  # noqa: BLE001
        cost = 0.0
    return Usage(input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)
