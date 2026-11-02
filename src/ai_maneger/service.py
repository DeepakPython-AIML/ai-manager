"""Async run execution, approvals and audit logging."""
import asyncio
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import Agent, Run, RunEvent, now, sessions
from .engines import ENGINE_ORDER, ENGINES
from .llm import GuardrailBlocked, LLMError
from .workflow import AgentConfig, AgentInactive, RunContext, State

log = logging.getLogger(__name__)

IN_FLIGHT = ("queued", "running", "switching_engine", "executing")
_tasks: set[asyncio.Task] = set()


def spawn(run_id: str) -> None:
    # In production this is an SQS message consumed by an ECS worker; the interface is the same.
    task = asyncio.create_task(execute_run(run_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain() -> None:
    """Wait for background runs. Used on shutdown and by tests."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def record(
    tenant_id: str, run_id: str | None, type_: str, message: str,
    data: dict[str, Any] | None = None, actor: str = "agent",
) -> None:
    async with sessions()() as s:
        s.add(RunEvent(tenant_id=tenant_id, run_id=run_id, type=type_, actor=actor, message=message, data=data))
        await s.commit()


async def _patch(run_id: str, **fields: Any) -> None:
    async with sessions()() as s:
        await s.execute(update(Run).where(Run.id == run_id).values(updated_at=now(), **fields))
        await s.commit()


async def transition(session: AsyncSession, run: Run, source: tuple[str, ...], **fields: Any) -> bool:
    """Compare-and-swap on status, so concurrent decisions or retries can't both win."""
    result = await session.execute(
        update(Run).where(Run.id == run.id, Run.status.in_(source)).values(updated_at=now(), **fields)
    )
    await session.commit()
    await session.refresh(run)
    return result.rowcount == 1


async def _run_engine(name: str, run: Run, state: State, ctx: RunContext, status: str) -> State:
    """Run one engine. LLMError propagates at once: the model clients have already retried it."""
    s = get_settings()
    engine = ENGINES[name]
    for attempt in range(1, s.run_attempts + 1):
        run.attempts += 1
        await _patch(run.id, status=status, attempts=run.attempts)
        await record(run.tenant_id, run.id, "attempt_started",
                     f"{engine.label}: attempt {attempt}/{s.run_attempts}", actor="system")
        try:
            return await asyncio.wait_for(engine.run(state, ctx), s.run_timeout_s)
        except (LLMError, GuardrailBlocked, AgentInactive):
            raise
        except Exception as e:  # noqa: BLE001 - a run failure must never kill the worker
            log.exception("run %s attempt %s failed", run.id, attempt)
            await record(run.tenant_id, run.id, "attempt_failed", f"{type(e).__name__}: {e}"[:500], actor="system")
            if attempt == s.run_attempts:
                raise
            await asyncio.sleep(2 ** attempt)
    raise AssertionError("unreachable")


async def _switch_engine(run: Run, target: str, reason: str) -> None:
    # The pause is the window in which the UI shows its switching dialog.
    label = ENGINES[target].label
    await _patch(run.id, status="switching_engine", fallback_reason=reason)
    await record(run.tenant_id, run.id, "engine_switching", f"{reason}. Switching to {label}", actor="system")
    await asyncio.sleep(get_settings().engine_switch_delay_s)


async def _check_active(agent_id: str) -> None:
    async with sessions()() as s:
        agent = await s.get(Agent, agent_id)
    if not agent.enabled:
        raise AgentInactive("Agent was stopped before the action ran")


async def execute_run(run_id: str) -> None:
    async with sessions()() as session:
        run = await session.get(Run, run_id)
        agent = await session.get(Agent, run.agent_id)
    resuming = run.decision == "approved"
    ctx = RunContext(
        agent=AgentConfig(agent.system_prompt, agent.model_id, agent.fallback_model_id,
                          agent.approval_policy, agent.allowed_actions),
        emit=lambda type_, message, data=None: record(run.tenant_id, run_id, type_, message, data),
        save=lambda **fields: _patch(run_id, **fields),
        check_active=lambda: _check_active(agent.id),
    )
    state = {"input": run.input, "decision": run.decision, "analysis": run.analysis, "proposal": run.proposal}
    # An approved action stays on the engine that proposed it; anything else starts at Bedrock again.
    order = [run.engine] if resuming else ENGINE_ORDER
    status = "executing" if resuming else "running"
    if not resuming:
        await _patch(run_id, fallback_reason=None)
    error = "unknown"
    for name, fallback in zip(order, [*order[1:], None]):
        await _patch(run_id, engine=name)
        try:
            result = await _run_engine(name, run, state, ctx, status)
        except LLMError as e:
            error = f"{ENGINES[name].label}: {e}"[:500]
            log.warning("run %s: %s", run_id, error)
            await record(run.tenant_id, run_id, "attempt_failed", error, actor="system")
            if fallback:
                await _switch_engine(run, fallback, str(e))
                continue
            break
        except GuardrailBlocked as e:
            # Final, on any engine: switching would just send blocked text to the other model.
            await _patch(run_id, status="blocked", error=e.message)
            await record(run.tenant_id, run_id, "guardrail_blocked", e.message,
                         {"engine": name, "policies": e.policies}, actor="system")
            return
        except AgentInactive as e:
            error = str(e)
            break
        except Exception as e:  # noqa: BLE001 - only model failures switch engine, never action failures
            error = f"{type(e).__name__}: {e}"[:500]
            break
        if result.get("outcome"):
            await _patch(run_id, status="completed", error=None)
            await record(run.tenant_id, run_id, "completed", "Run completed", actor="system")
        else:
            await _patch(run_id, status="awaiting_approval", error=None)
            await record(run.tenant_id, run_id, "approval_requested", "Waiting for human approval", actor="system")
        return
    await _patch(run_id, status="failed", error=error)
    await record(run.tenant_id, run_id, "failed", error, actor="system")


async def recover_runs() -> None:
    """Re-queue runs a previous process left in flight; decisions and proposals are already durable."""
    async with sessions()() as s:
        ids = (await s.scalars(select(Run.id).where(Run.status.in_(IN_FLIGHT)))).all()
    for run_id in ids:
        log.info("recovering run %s", run_id)
        spawn(run_id)
