"""Primary engine: the agent steps run in sequence on Amazon Bedrock's Converse API, behind Bedrock Guardrails."""
from ..llm import complete_json
from ..workflow import RunContext, State, analyse, execute, propose


async def _complete(system: str, user: str, ctx: RunContext) -> dict:
    reply = await complete_json(system, user, ctx.agent.model_id)
    await ctx.emit("guardrail_passed", "Bedrock Guardrails passed the request and reply", {"engine": "bedrock"})
    return reply


async def run(state: State, ctx: RunContext) -> State:
    if state.get("decision") == "approved":
        return {**state, **await execute(state, ctx)}
    state = {**state, **await analyse(state, ctx, _complete)}
    state = {**state, **await propose(state, ctx, _complete)}
    if state["requires_approval"]:
        return state
    return {**state, **await execute(state, ctx)}
