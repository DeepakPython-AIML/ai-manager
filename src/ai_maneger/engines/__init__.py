"""Interchangeable agent engines. ENGINE_ORDER is tried first to last for every new run."""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..config import get_settings
from ..workflow import RunContext, State
from . import bedrock_engine, langgraph_engine


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
    "bedrock": Engine("bedrock", "Amazon Bedrock", "primary", bedrock_engine.run),
    "langgraph": Engine("langgraph", "LangGraph + LangChain", "fallback", langgraph_engine.run),
}
ENGINE_ORDER = ["bedrock", "langgraph"]
