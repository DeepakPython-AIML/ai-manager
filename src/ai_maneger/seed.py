from sqlalchemy import func, select

from .config import get_settings
from .db import Agent, Tenant, User, sessions
from .security import hash_password
from .workflow import ACTIONS

DEMO_PASSWORD = "demo1234"
IT_SUPPORT_PROMPT = (
    "You are the corporate IT Support Agent. Resolve issues with the least privileged action "
    "that fixes them and prefer escalation when unsure."
)


def default_agent(tenant_id: str, user_id: str) -> Agent:
    return Agent(
        tenant_id=tenant_id,
        name="IT Support Agent",
        description="Triages IT issues, proposes a fix and acts after human approval.",
        system_prompt=IT_SUPPORT_PROMPT,
        allowed_actions=list(ACTIONS),
        created_by=user_id,
    )


async def seed() -> None:
    if not get_settings().seed_demo:
        return
    async with sessions()() as s:
        if await s.scalar(select(func.count()).select_from(Tenant)):
            return
        for org, domain in (("Acme Corp", "acme.test"), ("Globex Inc", "globex.test")):
            tenant = Tenant(name=org)
            s.add(tenant)
            await s.flush()
            users = [
                User(tenant_id=tenant.id, email=f"{r}@{domain}", name=f"{r.title()} ({org})", role=r,
                     password_hash=hash_password(DEMO_PASSWORD))
                for r in ("admin", "operator", "approver", "viewer")
            ]
            s.add_all(users)
            await s.flush()
            s.add(default_agent(tenant.id, users[0].id))
        await s.commit()
