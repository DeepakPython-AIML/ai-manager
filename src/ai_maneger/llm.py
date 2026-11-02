"""Amazon Bedrock access with retries for transient failures."""
import asyncio
import json
import logging
import re
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from .bedrock_guardrail import flagged_policies
from .config import get_settings

log = logging.getLogger(__name__)

PERMANENT_CODES = {
    "AccessDeniedException", "ValidationException", "ResourceNotFoundException", "UnrecognizedClientException",
}


class LLMError(Exception):
    """Bedrock call failed. The message is safe to show to tenants (no ARNs or account ids)."""


class LLMPermanentError(LLMError):
    """Failure a retry cannot fix, such as missing permissions or an unknown model."""


class GuardrailBlocked(Exception):
    """A guardrail refused the request or reply. A policy decision, so it is never retried or rerouted."""

    def __init__(self, message: str, policies: list[str]):
        super().__init__(message)
        self.message = message
        self.policies = policies


def _retryable(exc: BaseException) -> bool:
    return not isinstance(exc, (LLMPermanentError, GuardrailBlocked))


@lru_cache
def _bedrock():
    s = get_settings()
    creds = {}
    if s.aws_access_key and s.aws_secret_key:
        creds = {
            "aws_access_key_id": s.aws_access_key.get_secret_value(),
            "aws_secret_access_key": s.aws_secret_key.get_secret_value(),
        }
    # With no explicit keys boto3 uses the ECS task role, which is what production should do.
    return boto3.client(
        "bedrock-runtime", region_name=s.aws_region,
        config=Config(read_timeout=s.llm_timeout_s, connect_timeout=5, retries={"max_attempts": 1}),
        **creds,
    )


def _converse(system: str, user: str, model_id: str | None) -> str:
    s = get_settings()
    if not s.bedrock_guardrail_id:  # fail closed: no Bedrock model call happens without a guardrail
        raise LLMPermanentError("Bedrock Guardrail is not configured")
    try:
        r = _bedrock().converse(
            modelId=model_id or s.bedrock_model_id,
            system=[{"text": system}],
            # guardContent limits the checks to the untrusted text, so the system prompt can't trip them.
            messages=[{"role": "user", "content": [{"guardContent": {"text": {"text": user}}}]}],
            inferenceConfig={"maxTokens": 800, "temperature": 0.1},
            guardrailConfig={
                "guardrailIdentifier": s.bedrock_guardrail_id,
                "guardrailVersion": s.bedrock_guardrail_version,
                "trace": "enabled",
            },
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        log.warning("Bedrock call failed: %s", e)  # full detail stays in the server logs
        if code in PERMANENT_CODES:
            raise LLMPermanentError(f"Bedrock {code}") from e
        raise LLMError(f"Bedrock {code}") from e
    except BotoCoreError as e:
        log.warning("Bedrock call failed: %s", e)
        raise LLMError(f"Bedrock {type(e).__name__}") from e
    text = r["output"]["message"]["content"][0]["text"]
    if r.get("stopReason") == "guardrail_intervened":
        raise GuardrailBlocked(text, flagged_policies(r.get("trace", {}).get("guardrail")))
    return text


def parse_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMError("Bedrock returned no JSON object")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise LLMError("Bedrock returned invalid JSON") from e


async def complete_json(system: str, user: str, model_id: str | None = None) -> dict[str, Any]:
    """Return the parsed JSON reply. Raises LLMError once retries are exhausted."""
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(get_settings().llm_attempts),
        wait=wait_exponential_jitter(multiplier=0.5, max=4),
        retry=retry_if_exception(_retryable),
        reraise=True,
    ):
        with attempt:
            return parse_json(await asyncio.to_thread(_converse, system, user, model_id))
    raise LLMError("Bedrock retries exhausted")
