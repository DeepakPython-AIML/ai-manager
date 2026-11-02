"""Guardrails for the LangGraph engine, as LangChain middleware around every model call.

    request -> credentials and PII -> blocked topics and injection -> model -> credentials and PII -> leak check

These are fixed rules, kept in the same policy areas as the Bedrock Guardrail. They run in this process
because the fallback must keep working when AWS is the thing that failed.
"""
import re

from langchain.agents.middleware import AgentMiddleware, PIIMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from ..llm import GuardrailBlocked

BLOCKED_REQUEST = "This request was blocked by the safety policy, so no action was taken."
BLOCKED_REPLY = "The agent's reply was blocked by the safety policy, so no action was taken."

# The value must be present: "my password is expired" is a normal support request.
SENSITIVE_DATA = {
    "password": r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*\S{4,}",
    "aws_access_key": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "us_ssn": r"\b\d{3}-\d{2}-\d{4}\b",
}
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


def _last_text(state: dict, kind: type) -> str:
    message = next((m for m in reversed(state["messages"]) if isinstance(m, kind)), None)
    return message.text if message else ""


class RequestRules(AgentMiddleware):
    def before_model(self, state, runtime):
        text = _last_text(state, HumanMessage)
        policies = [name for name, rule in REQUEST_RULES.items() if rule.search(text)]
        if policies:
            raise GuardrailBlocked(BLOCKED_REQUEST, policies)


class ReplyRules(AgentMiddleware):
    def after_model(self, state, runtime):
        if PROMPT_LEAK.search(_last_text(state, AIMessage)):
            raise GuardrailBlocked(BLOCKED_REPLY, ["prompt_leak"])


def _data_rule(pii_type: str, detector: str | None = None) -> PIIMiddleware:
    return PIIMiddleware(pii_type, strategy="block", detector=detector, apply_to_input=True, apply_to_output=True)


MIDDLEWARE = [
    _data_rule("credit_card"),
    *(_data_rule(name, pattern) for name, pattern in SENSITIVE_DATA.items()),
    RequestRules(),
    ReplyRules(),
]
