"""Primary engine: the agent steps run in sequence on Amazon Bedrock's Converse API."""
from ..llm import complete_json
from ..workflow import RunContext, State, analyse, execute, propose


async def _complete(system: str, user: str, ctx: RunContext) -> dict:
    return await complete_json(system, user, ctx.agent.model_id)


async def run(state: State, ctx: RunContext) -> State:
    if state.get("decision") == "approved":
        return {**state, **await execute(state, ctx)}
    state = {**state, **await analyse(state, ctx, _complete)}
    state = {**state, **await propose(state, ctx, _complete)}
    if state["requires_approval"]:
        return state
    return {**state, **await execute(state, ctx)}
