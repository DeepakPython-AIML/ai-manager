from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .workflow import ACTIONS

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
Role = Literal["admin", "operator", "approver", "viewer"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Login(BaseModel):
    email: Email
    password: str = Field(max_length=128)


class Signup(BaseModel):
    org_name: Name
    name: Name
    email: Email
    password: Password


class UserOut(ORM):
    id: str
    tenant_id: str
    email: str
    name: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    user: UserOut


class TenantOut(ORM):
    id: str
    name: str
    created_at: datetime


class TenantUpdate(BaseModel):
    name: Name


class MemberCreate(BaseModel):
    name: Name
    email: Email
    password: Password
    role: Role


class MemberUpdate(BaseModel):
    role: Role


def _check_actions(value: list[str] | None) -> list[str] | None:
    if value is not None:
        unknown = set(value) - set(ACTIONS)
        if unknown:
            raise ValueError(f"Unknown actions: {sorted(unknown)}")
        if not value:
            raise ValueError("At least one action is required")
    return value


class AgentCreate(BaseModel):
    name: Name
    description: str = Field(default="", max_length=1000)
    model_id: str | None = Field(default=None, max_length=200)
    fallback_model_id: str | None = Field(default=None, max_length=200)
    system_prompt: str = Field(default="", max_length=4000)
    approval_policy: Literal["sensitive", "always"] = "sensitive"
    allowed_actions: list[str] = Field(default_factory=lambda: list(ACTIONS))

    _actions = field_validator("allowed_actions")(_check_actions)


class AgentUpdate(BaseModel):
    name: Name | None = None
    description: str | None = Field(default=None, max_length=1000)
    model_id: str | None = Field(default=None, max_length=200)
    fallback_model_id: str | None = Field(default=None, max_length=200)
    system_prompt: str | None = Field(default=None, max_length=4000)
    approval_policy: Literal["sensitive", "always"] | None = None
    allowed_actions: list[str] | None = None
    enabled: bool | None = None

    _actions = field_validator("allowed_actions")(_check_actions)


class AgentOut(ORM):
    id: str
    name: str
    description: str
    kind: str
    model_id: str | None
    fallback_model_id: str | None
    system_prompt: str
    approval_policy: str
    allowed_actions: list[str]
    enabled: bool
    created_at: datetime


class AgentSummary(AgentOut):
    status: Literal["idle", "busy", "awaiting_approval", "disabled"]
    total_runs: int


class RunCreate(BaseModel):
    input: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=1000)


class RunOut(ORM):
    id: str
    agent_id: str
    requested_by: str
    input: str
    status: str
    engine: str | None
    fallback_reason: str | None
    analysis: dict[str, Any] | None
    proposal: dict[str, Any] | None
    outcome: dict[str, Any] | None
    decision: str | None
    decided_by: str | None
    decision_note: str | None
    decided_at: datetime | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime


class EventOut(ORM):
    id: str
    run_id: str | None
    type: str
    actor: str
    message: str
    data: dict[str, Any] | None
    created_at: datetime


class RunDetail(RunOut):
    events: list[EventOut]
