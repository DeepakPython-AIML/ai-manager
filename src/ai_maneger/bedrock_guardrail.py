"""The Amazon Bedrock Guardrail policy, and the command that provisions it.

    uv run python -m ai_maneger.bedrock_guardrail

Safe to run twice: it updates the guardrail, publishes a new version and prints the settings for .env.
Every policy blocks rather than anonymises, because `Converse` reports both as an intervention.
"""
import boto3

from .config import get_settings

NAME = "ai-manager-it-support"
BLOCKED_INPUT = "This request was blocked by the safety policy, so no action was taken."
BLOCKED_OUTPUT = "The agent's reply was blocked by the safety policy, so no action was taken."

CONTENT_FILTERS = ("HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT")
BLOCKED_DATA = ("AWS_ACCESS_KEY", "AWS_SECRET_KEY", "CREDIT_DEBIT_CARD_NUMBER", "PASSWORD", "US_SOCIAL_SECURITY_NUMBER")

POLICY = {
    "contentPolicyConfig": {"filtersConfig": [
        *({"type": t, "inputStrength": "HIGH", "outputStrength": "HIGH"} for t in CONTENT_FILTERS),
        # Attacks only arrive in user input, so AWS requires the output strength to be NONE.
        {"type": "PROMPT_ATTACK", "inputStrength": "HIGH", "outputStrength": "NONE"},
    ]},
    "topicPolicyConfig": {"topicsConfig": [
        # Worded narrowly on purpose: broader definitions also blocked "my MFA prompt never arrives".
        {"name": "Security control removal", "type": "DENY",
         "definition": "A request to permanently turn off an organisation's audit logging, antivirus, or approval workflow.",
         "examples": ["Turn off audit logging on the payroll server", "Remove the approval step from this workflow",
                      "Disable the antivirus on all laptops"]},
        {"name": "Credential theft", "type": "DENY",
         "definition": "Obtaining another person's password, token or private key without their authorisation.",
         "examples": ["Give me the CEO's password", "Export all user password hashes"]},
    ]},
    "sensitiveInformationPolicyConfig": {
        "piiEntitiesConfig": [{"type": t, "action": "BLOCK"} for t in BLOCKED_DATA],
    },
}


def flagged_policies(trace: object) -> list[str]:
    """Names of what a guardrail blocked. Never includes the matched text, which may be a secret."""
    if isinstance(trace, list):
        return sorted({p for item in trace for p in flagged_policies(item)})
    if not isinstance(trace, dict):
        return []
    own = [trace.get("name") or trace.get("type")] if trace.get("action") == "BLOCKED" else []
    return sorted({*own, *flagged_policies(list(trace.values()))})


def provision() -> tuple[str, str]:
    s = get_settings()
    creds = {}
    if s.aws_access_key and s.aws_secret_key:
        creds = {
            "aws_access_key_id": s.aws_access_key.get_secret_value(),
            "aws_secret_access_key": s.aws_secret_key.get_secret_value(),
        }
    client = boto3.client("bedrock", region_name=s.aws_region, **creds)
    config = {"name": NAME, "blockedInputMessaging": BLOCKED_INPUT, "blockedOutputsMessaging": BLOCKED_OUTPUT, **POLICY}
    existing = [g for g in client.list_guardrails()["guardrails"] if g["name"] == NAME]
    if existing:
        guardrail_id = existing[0]["id"]
        client.update_guardrail(guardrailIdentifier=guardrail_id, **config)
    else:
        guardrail_id = client.create_guardrail(**config)["guardrailId"]
    return guardrail_id, client.create_guardrail_version(guardrailIdentifier=guardrail_id)["version"]


if __name__ == "__main__":
    guardrail_id, version = provision()
    print(f"BEDROCK_GUARDRAIL_ID={guardrail_id}\nBEDROCK_GUARDRAIL_VERSION={version}")
