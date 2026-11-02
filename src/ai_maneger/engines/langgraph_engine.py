"""Fallback engine: a LangGraph workflow whose model calls go through LangChain.

    START -> (router) -> analyse -> propose -> (gate) -> END [awaiting approval]
                 |                                |
                 +------- approved ------> execute <--- no approval needed

LangGraph only orchestrates, so this engine still needs a model: LangChain's ChatGroq, which keeps
the fallback independent of AWS when Bedrock is the thing that failed. Each model call is a LangChain
agent, so guardrail middleware wraps it.
"""
from functools import lru_cache

from langchain.agents import create_agent
from langchain.agents.middleware import PIIDetectionError
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph

from ..config import get_settings
from ..llm import GuardrailBlocked, LLMError, LLMPermanentError, parse_json
from ..workflow import RunContext, State, analyse, execute, propose
from .guardrail_middleware import MIDDLEWARE


@lru_cache
def _chat(model: str):
    s = get_settings()
    if not s.groq_api_key:
        raise LLMPermanentError("LangGraph fallback needs GROQ_API_KEY")
    return ChatGroq(
        model=model, api_key=s.groq_api_key, temperature=0.1, max_tokens=800,
        timeout=s.llm_timeout_s, max_retries=s.llm_attempts,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


@lru_cache
def _agent(model: str):
    return create_agent(_chat(model), tools=[], middleware=MIDDLEWARE)


async def _complete(system: str, user: str, ctx: RunContext) -> dict:
    agent = _agent(ctx.agent.fallback_model_id or get_settings().groq_model)
    try:
        result = await agent.ainvoke({"messages": [SystemMessage(system), HumanMessage(user)]})
    except GuardrailBlocked:
        raise
    except PIIDetectionError as e:
        raise GuardrailBlocked("Sensitive data was blocked by the safety policy, so no action was taken.",
                               [e.pii_type]) from e
    except Exception as e:  # noqa: BLE001 - provider SDK errors have no shared base class
        raise LLMError(f"LangChain {type(e).__name__}") from e
    await ctx.emit("guardrail_passed", "Guardrail middleware passed the request and reply", {"engine": "langgraph"})
    return parse_json(result["messages"][-1].content)


def _ctx(config: RunnableConfig) -> RunContext:
    return config["configurable"]["ctx"]


async def _analyse(state: State, config: RunnableConfig) -> State:
    return await analyse(state, _ctx(config), _complete)


async def _propose(state: State, config: RunnableConfig) -> State:
    return await propose(state, _ctx(config), _complete)


async def _execute(state: State, config: RunnableConfig) -> State:
    return await execute(state, _ctx(config))


def _route(state: State) -> str:
    return "execute" if state.get("decision") == "approved" else "analyse"


def _gate(state: State) -> str:
    return END if state["requires_approval"] else "execute"


def build_graph():
    g = StateGraph(State)
    g.add_node("analyse", _analyse)
    g.add_node("propose", _propose)
    g.add_node("execute", _execute)
    g.add_conditional_edges(START, _route, ["analyse", "execute"])
    g.add_edge("analyse", "propose")
    g.add_conditional_edges("propose", _gate, ["execute", END])
    g.add_edge("execute", END)
    return g.compile()


graph = build_graph()


async def run(state: State, ctx: RunContext) -> State:
    return await graph.ainvoke(state, {"configurable": {"ctx": ctx}})
