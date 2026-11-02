"""Both engines are Strands Agents: the agent steps run in sequence and only the model and guardrail differ.

    bedrock: BedrockModel, behind a Bedrock Guardrail
    groq:    OpenAIModel pointed at Groq, behind guardrail middleware

Groq keeps the fallback independent of AWS when Bedrock is the thing that failed. Each model call gets a new
Agent with no tools: the model only proposes, and workflow.py decides what runs.
"""
import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from strands import Agent, ModelRetryStrategy
from strands.middleware import InvokeModelStage
from strands.models import BedrockModel
from strands.models.openai import OpenAIModel

from ..config import get_settings
from ..llm import GuardrailBlocked, LLMError, LLMPermanentError, parse_json
from ..workflow import Complete, RunContext, State, analyse, execute, propose
from .guardrail_middleware import bedrock_guardrail_gate, text_guardrails

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1"
PERMANENT_CODES = {
    "AccessDeniedException", "ValidationException", "ResourceNotFoundException", "UnrecognizedClientException",
}


class TransientRetry(ModelRetryStrategy):
    def is_retryable(self, exception: Exception) -> bool:
        if isinstance(exception, ClientError):
            return exception.response["Error"]["Code"] not in PERMANENT_CODES
        return isinstance(exception, BotoCoreError) or super().is_retryable(exception)


@lru_cache
def _bedrock_model(model_id: str) -> BedrockModel:
    s = get_settings()
    creds = {}
    if s.aws_access_key and s.aws_secret_key:
        creds = {
            "aws_access_key_id": s.aws_access_key.get_secret_value(),
            "aws_secret_access_key": s.aws_secret_key.get_secret_value(),
        }
    # With no explicit keys boto3 uses the ECS task role, which is what production should do.
    return BedrockModel(
        boto_session=boto3.Session(region_name=s.aws_region, **creds),
        boto_client_config=Config(read_timeout=s.llm_timeout_s, connect_timeout=5, retries={"max_attempts": 1}),
        model_id=model_id, streaming=False, temperature=0.1, max_tokens=800,
        guardrail_id=s.bedrock_guardrail_id, guardrail_version=s.bedrock_guardrail_version, guardrail_trace="enabled",
        # Limits the checks to the untrusted text, so the system prompt can't trip them.
        guardrail_latest_message=True,
    )


@lru_cache
def _groq_model(model_id: str) -> OpenAIModel:
    s = get_settings()
    if not s.groq_api_key:
        raise LLMPermanentError("Fallback needs GROQ_API_KEY")
    return OpenAIModel(
        client_args={"api_key": s.groq_api_key.get_secret_value(), "base_url": GROQ_URL, "timeout": s.llm_timeout_s},
        model_id=model_id,
        params={"temperature": 0.1, "max_tokens": 800, "response_format": {"type": "json_object"}},
    )


def _error(provider: str, e: Exception) -> LLMError:
    """Translate an SDK failure. The message is safe to show to tenants (no ARNs or account ids)."""
    log.warning("%s call failed: %s", provider, e)  # full detail stays in the server logs
    if isinstance(e, ClientError):
        code = e.response["Error"]["Code"]
        return (LLMPermanentError if code in PERMANENT_CODES else LLMError)(f"{provider} {code}")
    return LLMError(f"{provider} {type(e).__name__}")


async def _ask(model, guardrail, provider: str, system: str, user: str) -> dict:
    s = get_settings()
    agent = Agent(
        model=model, system_prompt=system, callback_handler=None,
        retry_strategy=TransientRetry(max_attempts=s.llm_attempts, initial_delay=1, max_delay=4),
    )
    agent.add_middleware(InvokeModelStage, guardrail)
    try:
        result = await agent.invoke_async(user)
    except GuardrailBlocked:
        raise
    except Exception as e:  # noqa: BLE001 - provider SDK errors have no shared base class
        raise _error(provider, e) from e
    return parse_json(str(result))


async def _bedrock(system: str, user: str, ctx: RunContext) -> dict:
    s = get_settings()
    if not s.bedrock_guardrail_id:  # fail closed: no Bedrock model call happens without a guardrail
        raise LLMPermanentError("Bedrock Guardrail is not configured")
    model = _bedrock_model(ctx.agent.model_id or s.bedrock_model_id)
    reply = await _ask(model, bedrock_guardrail_gate, "Bedrock", system, user)
    await ctx.emit("guardrail_passed", "Bedrock Guardrails passed the request and reply", {"engine": "bedrock"})
    return reply


async def _groq(system: str, user: str, ctx: RunContext) -> dict:
    model = _groq_model(ctx.agent.fallback_model_id or get_settings().groq_model)
    reply = await _ask(model, text_guardrails, "Groq", system, user)
    await ctx.emit("guardrail_passed", "Guardrail middleware passed the request and reply", {"engine": "groq"})
    return reply


def _engine(complete: Complete) -> Callable[[State, RunContext], Awaitable[State]]:
    async def run(state: State, ctx: RunContext) -> State:
        if state.get("decision") == "approved":
            return {**state, **await execute(state, ctx)}
        state = {**state, **await analyse(state, ctx, complete)}
        state = {**state, **await propose(state, ctx, complete)}
        if state["requires_approval"]:
            return state
        return {**state, **await execute(state, ctx)}

    return run


run_bedrock = _engine(_bedrock)
run_groq = _engine(_groq)
