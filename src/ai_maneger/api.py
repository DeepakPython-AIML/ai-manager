from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import schemas as sc
from .config import get_settings
from .db import Agent, Run, RunEvent, Tenant, User, get_session, now
from .security import Principal, current_principal, hash_password, issue_token, require, verify_password
from .engines import ENGINE_ORDER, ENGINES
from .seed import default_agent
from .service import IN_FLIGHT, record, spawn, transition
from .workflow import ACTIONS

router = APIRouter(prefix="/api")
Session = Depends(get_session)
MAX_PAGE = 200
# Compared against when the email is unknown, so login timing doesn't reveal which accounts exist.
_DUMMY_HASH = hash_password("timing-equaliser")


async def scoped(session: AsyncSession, model, id_: str, p: Principal):
    """Fetch a tenant-owned row. Other tenants' rows are a 404, so existence never leaks."""
    obj = await session.get(model, id_)
    if obj is None or obj.tenant_id != p.tenant_id:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


# Auth


@router.post("/auth/login", response_model=sc.TokenOut)
async def login(body: sc.Login, session: AsyncSession = Session):
    user = await session.scalar(select(User).where(User.email == body.email))
    if not verify_password(body.password, user.password_hash if user else _DUMMY_HASH) or not user:
        raise HTTPException(401, "Invalid email or password")
    await record(user.tenant_id, None, "login", f"{user.email} signed in", actor=user.id)
    return {"access_token": issue_token(user), "user": user}


@router.post("/auth/signup", response_model=sc.TokenOut, status_code=201)
async def signup(body: sc.Signup, session: AsyncSession = Session):
    tenant = Tenant(name=body.org_name)
    session.add(tenant)
    await session.flush()
    user = User(tenant_id=tenant.id, email=body.email, name=body.name, role="admin",
                password_hash=hash_password(body.password))
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Email already registered") from None
    session.add(default_agent(tenant.id, user.id))
    await session.commit()
    await record(tenant.id, None, "tenant_created", f"Organisation {tenant.name} created", actor=user.id)
    return {"access_token": issue_token(user), "user": user}


@router.get("/auth/me", response_model=sc.UserOut)
async def me(p: Principal = Depends(current_principal)):
    return sc.UserOut(id=p.user_id, tenant_id=p.tenant_id, email=p.email, name=p.name, role=p.role)


# Tenant


@router.get("/tenant", response_model=sc.TenantOut)
async def get_tenant(p: Principal = Depends(require("read")), session: AsyncSession = Session):
    return await session.get(Tenant, p.tenant_id)


@router.patch("/tenant", response_model=sc.TenantOut)
async def update_tenant(body: sc.TenantUpdate, p: Principal = Depends(require("manage_tenant")),
                        session: AsyncSession = Session):
    tenant = await session.get(Tenant, p.tenant_id)
    tenant.name = body.name
    await session.commit()
    await record(p.tenant_id, None, "tenant_updated", f"Renamed to {body.name}", actor=p.user_id)
    return tenant


@router.get("/tenant/members", response_model=list[sc.UserOut])
async def members(p: Principal = Depends(require("read")), session: AsyncSession = Session):
    return (await session.scalars(select(User).where(User.tenant_id == p.tenant_id).order_by(User.email))).all()


@router.post("/tenant/members", response_model=sc.UserOut, status_code=201)
async def add_member(body: sc.MemberCreate, p: Principal = Depends(require("manage_tenant")),
                     session: AsyncSession = Session):
    user = User(tenant_id=p.tenant_id, email=body.email, name=body.name, role=body.role,
                password_hash=hash_password(body.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Email already registered") from None
    await record(p.tenant_id, None, "member_added", f"{user.email} added as {user.role}", actor=p.user_id)
    return user


async def _keep_one_admin(session: AsyncSession, user: User) -> None:
    if user.role == "admin":
        admins = await session.scalar(
            select(func.count()).select_from(User).where(User.tenant_id == user.tenant_id, User.role == "admin")
        )
        if admins <= 1:
            raise HTTPException(409, "An organisation needs at least one admin")


@router.patch("/tenant/members/{user_id}", response_model=sc.UserOut)
async def update_member(user_id: str, body: sc.MemberUpdate, p: Principal = Depends(require("manage_tenant")),
                        session: AsyncSession = Session):
    user = await scoped(session, User, user_id, p)
    if body.role != "admin":
        await _keep_one_admin(session, user)
    user.role = body.role
    await session.commit()
    await record(p.tenant_id, None, "member_updated", f"{user.email} is now {user.role}", actor=p.user_id)
    return user


@router.delete("/tenant/members/{user_id}", status_code=204)
async def remove_member(user_id: str, p: Principal = Depends(require("manage_tenant")),
                        session: AsyncSession = Session):
    user = await scoped(session, User, user_id, p)
    await _keep_one_admin(session, user)
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    await record(p.tenant_id, None, "member_removed", f"{user.email} removed", actor=p.user_id)


# Agents


@router.get("/actions")
async def actions(_: Principal = Depends(require("read"))):
    return [{"id": k, **v} for k, v in ACTIONS.items()]


@router.get("/engines")
async def engines(_: Principal = Depends(require("read"))):
    return [
        {"id": e.id, "label": e.label, "role": e.role, "default_model": e.default_model}
        for e in (ENGINES[name] for name in ENGINE_ORDER)
    ]


@router.get("/agents", response_model=list[sc.AgentSummary])
async def list_agents(p: Principal = Depends(require("read")), session: AsyncSession = Session):
    agents = (await session.scalars(
        select(Agent).where(Agent.tenant_id == p.tenant_id).order_by(Agent.created_at.desc())
    )).all()
    rows = await session.execute(
        select(
            Run.agent_id,
            func.count(),
            func.sum(case((Run.status.in_(IN_FLIGHT), 1), else_=0)),
            func.sum(case((Run.status == "awaiting_approval", 1), else_=0)),
        ).where(Run.tenant_id == p.tenant_id).group_by(Run.agent_id)
    )
    counts = {r[0]: r[1:] for r in rows}
    out = []
    for a in agents:
        total, busy, waiting = counts.get(a.id, (0, 0, 0))
        status = "disabled" if not a.enabled else "busy" if busy else "awaiting_approval" if waiting else "idle"
        out.append(sc.AgentSummary(**sc.AgentOut.model_validate(a).model_dump(), status=status, total_runs=total))
    return out


@router.post("/agents", response_model=sc.AgentOut, status_code=201)
async def create_agent(body: sc.AgentCreate, p: Principal = Depends(require("manage_agents")),
                       session: AsyncSession = Session):
    agent = Agent(tenant_id=p.tenant_id, created_by=p.user_id, **body.model_dump())
    session.add(agent)
    await session.commit()
    await record(p.tenant_id, None, "agent_registered", f"Agent {agent.name} registered", actor=p.user_id)
    return agent


@router.get("/agents/{agent_id}", response_model=sc.AgentOut)
async def get_agent(agent_id: str, p: Principal = Depends(require("read")), session: AsyncSession = Session):
    return await scoped(session, Agent, agent_id, p)


@router.patch("/agents/{agent_id}", response_model=sc.AgentOut)
async def update_agent(agent_id: str, body: sc.AgentUpdate, p: Principal = Depends(require("manage_agents")),
                       session: AsyncSession = Session):
    agent = await scoped(session, Agent, agent_id, p)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(agent, key, value)
    await session.commit()
    await record(p.tenant_id, None, "agent_updated", f"Agent {agent.name} updated",
                 {"fields": sorted(changes)}, actor=p.user_id)
    return agent


# Runs


@router.post("/agents/{agent_id}/runs", response_model=sc.RunOut, status_code=202)
async def start_run(agent_id: str, body: sc.RunCreate, p: Principal = Depends(require("run")),
                    session: AsyncSession = Session):
    agent = await scoped(session, Agent, agent_id, p)
    if not agent.enabled:
        raise HTTPException(409, "Agent is disabled")
    run = Run(tenant_id=p.tenant_id, agent_id=agent.id, requested_by=p.user_id, input=body.input)
    session.add(run)
    await session.commit()
    await record(p.tenant_id, run.id, "submitted", "Request submitted", actor=p.user_id)
    spawn(run.id)
    return run


@router.get("/runs", response_model=list[sc.RunOut])
async def list_runs(agent_id: str | None = None, status: str | None = None,
                    limit: int = Query(default=50, ge=1, le=MAX_PAGE),
                    p: Principal = Depends(require("read")), session: AsyncSession = Session):
    query = select(Run).where(Run.tenant_id == p.tenant_id)
    if agent_id:
        query = query.where(Run.agent_id == agent_id)
    if status:
        query = query.where(Run.status == status)
    return (await session.scalars(query.order_by(Run.created_at.desc()).limit(limit))).all()


@router.get("/runs/{run_id}", response_model=sc.RunDetail)
async def get_run(run_id: str, p: Principal = Depends(require("read")), session: AsyncSession = Session):
    run = await scoped(session, Run, run_id, p)
    events = (await session.scalars(
        select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.tenant_id == p.tenant_id)
        .order_by(RunEvent.created_at)
    )).all()
    return sc.RunDetail(**sc.RunOut.model_validate(run).model_dump(),
                        events=[sc.EventOut.model_validate(e) for e in events])


@router.post("/runs/{run_id}/decision", response_model=sc.RunOut)
async def decide(run_id: str, body: sc.Decision, p: Principal = Depends(require("approve")),
                 session: AsyncSession = Session):
    run = await scoped(session, Run, run_id, p)
    self_decision = run.requested_by == p.user_id
    if self_decision and not get_settings().allow_self_approval:
        raise HTTPException(403, "You cannot decide on your own request")
    approved = body.decision == "approved"
    won = await transition(
        session, run, ("awaiting_approval",),
        status="executing" if approved else "rejected",
        decision=body.decision, decided_by=p.user_id, decision_note=body.note, decided_at=now(),
    )
    if not won:
        raise HTTPException(409, f"Run is '{run.status}', not awaiting approval")
    suffix = " on their own request" if self_decision else ""
    await record(p.tenant_id, run.id, body.decision, f"{p.email} {body.decision} the action{suffix}",
                 {"note": body.note, "self_decision": self_decision}, actor=p.user_id)
    if approved:
        spawn(run.id)
    return run


@router.post("/runs/{run_id}/retry", response_model=sc.RunOut, status_code=202)
async def retry(run_id: str, p: Principal = Depends(require("run")), session: AsyncSession = Session):
    run = await scoped(session, Run, run_id, p)
    if not await transition(session, run, ("failed",), status="queued", error=None):
        raise HTTPException(409, f"Run is '{run.status}', only failed runs can be retried")
    await record(p.tenant_id, run.id, "retried", f"{p.email} retried the run", actor=p.user_id)
    spawn(run.id)
    return run


# Audit


@router.get("/audit", response_model=list[sc.EventOut])
async def audit(limit: int = Query(default=100, ge=1, le=MAX_PAGE), p: Principal = Depends(require("audit")),
                session: AsyncSession = Session):
    return (await session.scalars(
        select(RunEvent).where(RunEvent.tenant_id == p.tenant_id).order_by(RunEvent.created_at.desc()).limit(limit)
    )).all()
