"""Interchangeable agent engines. ENGINE_ORDER is tried first to last for every new run."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..config import get_settings
from ..workflow import RunContext, State
from .strands_engine import run_bedrock, run_groq


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    role: str
    run: Callable[[State, RunContext], Awaitable[State]]

    @property
    def default_model(self) -> str:
        s = get_settings()
        return s.bedrock_model_id if self.id == "bedrock" else s.groq_model


ENGINES = {
    "bedrock": Engine("bedrock", "Amazon Bedrock", "primary", run_bedrock),
    "groq": Engine("groq", "Groq", "fallback", run_groq),
}
ENGINE_ORDER = ["bedrock", "groq"]
# Runs saved before the move to Strands can still be approved, and resume on the engine that replaced theirs.
RENAMED_ENGINES = {"langgraph": "groq"}
