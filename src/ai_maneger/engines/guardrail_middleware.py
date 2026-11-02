"""Guardrails as Strands middleware around every model call.

Bedrock checks its own calls, so `bedrock_guardrail_gate` only turns an intervention into a final block:
left alone, Strands would return the block message as if it were the model's reply.

`text_guardrails` protects the Groq engine with fixed rules in the same policy areas as the Bedrock
Guardrail. They run in this process because the fallback must keep working when AWS has failed.

    request -> sensitive data -> blocked topics and injection -> model -> sensitive data -> leak check
"""
import re

from strands.middleware import InvokeModelContext, ModelStopReason
from strands.types.content import Message

from ..bedrock_guardrail import flagged_policies
from ..llm import GuardrailBlocked

BLOCKED_REQUEST = "This request was blocked by the safety policy, so no action was taken."
BLOCKED_REPLY = "The agent's reply was blocked by the safety policy, so no action was taken."

# The value must be present: "my password is expired" is a normal support request.
SENSITIVE_DATA = {
    "password": re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*\S{4,}"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "us_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}
CARD_NUMBER = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
REQUEST_RULES = {
    "prompt_injection": re.compile(
        r"(?i)\b(?:ignore|disregard|forget|override)\b.{0,40}\b(?:instructions?|rules?|prompts?|guardrails?)\b"
        r"|\b(?:reveal|show|print|repeat)\b.{0,30}\bsystem prompt\b"
        r"|\b(?:jailbreak|developer mode|DAN mode)\b"
    ),
    "security_bypass": re.compile(
        r"(?i)\b(?:bypass|disable|turn off|skip|circumvent)\b.{0,40}"
        r"\b(?:mfa|2fa|audit|logging|approvals?|security|antivirus|edr)\b"
    ),
    "credential_theft": re.compile(
        r"(?i)\b(?:steal|dump|exfiltrate|harvest|crack)\b.{0,40}\b(?:passwords?|credentials?|tokens?|hashes|keys?)\b"
    ),
}
PROMPT_LEAK = re.compile(r"(?i)untrusted user data|never follow instructions")


def _text(message: Message) -> str:
    return "".join(block.get("text", "") for block in message["content"])


def _is_card(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)][::-1]
    return sum(d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2) for i, d in enumerate(digits)) % 10 == 0


def _sensitive_data(text: str) -> list[str]:
    found = [name for name, rule in SENSITIVE_DATA.items() if rule.search(text)]
    return [*found, "credit_card"] if any(_is_card(m) for m in CARD_NUMBER.findall(text)) else found


def _check_request(text: str) -> None:
    policies = _sensitive_data(text) + [name for name, rule in REQUEST_RULES.items() if rule.search(text)]
    if policies:
        raise GuardrailBlocked(BLOCKED_REQUEST, policies)


def _check_reply(text: str) -> None:
    policies = _sensitive_data(text) + (["prompt_leak"] if PROMPT_LEAK.search(text) else [])
    if policies:
        raise GuardrailBlocked(BLOCKED_REPLY, policies)


async def text_guardrails(context: InvokeModelContext, next_fn):
    _check_request(_text(context.messages[-1]))
    async for event in next_fn(context):
        if isinstance(event, ModelStopReason):
            _check_reply(_text(event.message))
        yield event


async def bedrock_guardrail_gate(context: InvokeModelContext, next_fn):
    trace = None
    async for event in next_fn(context):
        trace = event.get("event", {}).get("metadata", {}).get("trace", trace)
        if isinstance(event, ModelStopReason) and event.stop_reason == "guardrail_intervened":
            raise GuardrailBlocked(_text(event.message), flagged_policies((trace or {}).get("guardrail")))
        yield event
