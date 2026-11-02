from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", populate_by_name=True)

    env: str = "dev"
    database_url: str = f"sqlite+aiosqlite:///{ROOT / 'data.db'}"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Auth: "local" issues HS256 JWTs itself, "cognito" verifies Cognito-issued JWTs via JWKS.
    auth_mode: str = "local"
    jwt_secret: SecretStr = SecretStr("dev-insecure-secret-change-me-in-any-real-env")
    jwt_ttl_minutes: int = 480
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""

    # AWS / Bedrock. The .env uses AWS_ACCESS_KEY / AWS_ACCESS_SECRETE; standard names also work.
    aws_access_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("AWS_ACCESS_KEY", "AWS_ACCESS_KEY_ID")
    )
    aws_secret_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("AWS_ACCESS_SECRETE", "AWS_SECRET_ACCESS_KEY")
    )
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "us.amazon.nova-lite-v1:0"
    # Created by `python -m ai_maneger.bedrock_guardrail`. Without it, Bedrock refuses to call a model.
    bedrock_guardrail_id: str = ""
    bedrock_guardrail_version: str = "1"

    # Fallback engine (LangGraph + LangChain), used only when Bedrock fails.
    groq_api_key: SecretStr | None = None
    groq_model: str = "openai/gpt-oss-20b"
    engine_switch_delay_s: float = 3

    llm_timeout_s: float = 30
    llm_attempts: int = 2

    run_timeout_s: float = 120
    run_attempts: int = 2
    # False enforces separation of duties: nobody can decide on a request they submitted.
    allow_self_approval: bool = True
    seed_demo: bool = True

    def check(self) -> None:
        if self.env == "prod" and self.jwt_secret.get_secret_value().startswith("dev-insecure"):
            raise RuntimeError("JWT_SECRET must be set in prod")


@lru_cache
def get_settings() -> Settings:
    return Settings()
