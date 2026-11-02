"""Model errors and reply parsing shared by the engines."""
import json
import re
from typing import Any


class LLMError(Exception):
    """A model call failed. The message is safe to show to tenants (no ARNs or account ids)."""


class LLMPermanentError(LLMError):
    """Failure a retry cannot fix, such as missing permissions or an unknown model."""


class GuardrailBlocked(Exception):
    """A guardrail refused the request or reply. A policy decision, so it is never retried or rerouted."""

    def __init__(self, message: str, policies: list[str]):
        super().__init__(message)
        self.message = message
        self.policies = policies


def parse_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMError("Model returned no JSON object")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise LLMError("Model returned invalid JSON") from e
