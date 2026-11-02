import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/test.db"
os.environ["ENGINE_SWITCH_DELAY_S"] = "0"

import json
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from botocore.exceptions import ClientError
from sqlalchemy import update

from ai_maneger import service
from ai_maneger.db import Agent, init_db, sessions
from ai_maneger.main import app
from ai_maneger.seed import DEMO_PASSWORD, seed
from ai_maneger.workflow import needs_approval, sanitise_action

ISSUE = "My account is locked and I can't access the company portal."


def reply(payload: dict) -> dict:
    return {"output": {"message": {"content": [{"text": json.dumps(payload)}]}}}


def aws_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "arn:aws:iam::123456789012:user/x"}}, "Converse")


class FakeBedrock:
    """Stands in for the bedrock-runtime client: no network or AWS credentials in tests."""

    def __init__(self):
        self.calls = 0
        self.failures: list[Exception] = []
        self.action = "unlock_account"

    def converse(self, **kwargs):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        if "triage IT support" in kwargs["system"][0]["text"]:
            return reply({"category": "access", "severity": "high", "summary": "Account locked"})
        return reply({"action": self.action, "resolution": "Unlock it", "target": "requester", "confidence": 0.9})


class FakeChat:
    """Stands in for LangChain's ChatGroq in the LangGraph engine."""

    def __init__(self):
        self.calls = 0
        self.fail = False

    async def ainvoke(self, messages):
        self.calls += 1
        if self.fail:
            raise ConnectionError("groq down")
        if "triage IT support" in messages[0].content:
            payload = {"category": "access", "severity": "high", "summary": "Locked (fallback)"}
        else:
            payload = {"action": "unlock_account", "resolution": "Unlock it", "target": "requester"}
        return SimpleNamespace(content=json.dumps(payload))


@pytest.fixture(autouse=True)
def bedrock(monkeypatch):
    fake = FakeBedrock()
    monkeypatch.setattr("ai_maneger.llm._bedrock", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def chat(monkeypatch):
    fake = FakeChat()
    monkeypatch.setattr("ai_maneger.engines.langgraph_engine._chat", lambda _model: fake)
    return fake


@pytest_asyncio.fixture
async def client():
    await init_db()
    await seed()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def login(c, email):
    r = await c.post("/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def start(c, headers, text=ISSUE):
    agent = (await c.get("/api/agents", headers=headers)).json()[0]
    r = await c.post(f"/api/agents/{agent['id']}/runs", json={"input": text}, headers=headers)
    assert r.status_code == 202
    await service.drain()
    return (await c.get(f"/api/runs/{r.json()['id']}", headers=headers)).json()


@pytest.mark.asyncio
async def test_approval_flow_executes_simulated_action(client):
    op, approver = await login(client, "operator@acme.test"), await login(client, "approver@acme.test")
    run = await start(client, op)
    assert run["status"] == "awaiting_approval"
    assert run["proposal"]["action"] == "unlock_account" and run["outcome"] is None

    r = await client.post(f"/api/runs/{run['id']}/decision", json={"decision": "approved"}, headers=approver)
    assert r.status_code == 200
    await service.drain()
    done = (await client.get(f"/api/runs/{run['id']}", headers=op)).json()
    assert done["status"] == "completed" and done["outcome"]["simulated"] is True
    assert {"submitted", "analysed", "proposed", "approved", "executed", "completed"} <= {
        e["type"] for e in done["events"]
    }


@pytest.mark.asyncio
async def test_rejection_never_executes_and_second_decision_conflicts(client):
    op, approver = await login(client, "operator@acme.test"), await login(client, "approver@acme.test")
    run = await start(client, op)
    url = f"/api/runs/{run['id']}/decision"
    assert (await client.post(url, json={"decision": "rejected"}, headers=approver)).status_code == 200
    assert (await client.post(url, json={"decision": "approved"}, headers=approver)).status_code == 409
    await service.drain()
    done = (await client.get(f"/api/runs/{run['id']}", headers=op)).json()
    assert done["status"] == "rejected" and done["outcome"] is None


@pytest.mark.asyncio
async def test_tenant_isolation(client):
    acme, globex = await login(client, "operator@acme.test"), await login(client, "admin@globex.test")
    run = await start(client, acme)
    assert (await client.get(f"/api/runs/{run['id']}", headers=globex)).status_code == 404
    r = await client.post(f"/api/runs/{run['id']}/decision", json={"decision": "approved"}, headers=globex)
    assert r.status_code == 404
    assert (await client.get(f"/api/agents/{run['agent_id']}", headers=globex)).status_code == 404
    assert run["id"] not in [x["id"] for x in (await client.get("/api/runs", headers=globex)).json()]


@pytest.mark.asyncio
async def test_rbac_and_separation_of_duties(client):
    viewer, admin = await login(client, "viewer@acme.test"), await login(client, "admin@acme.test")
    agent = (await client.get("/api/agents", headers=viewer)).json()[0]
    r = await client.post(f"/api/agents/{agent['id']}/runs", json={"input": ISSUE}, headers=viewer)
    assert r.status_code == 403
    run = await start(client, admin)
    r = await client.post(f"/api/runs/{run['id']}/decision", json={"decision": "approved"}, headers=admin)
    assert r.status_code == 403  # requester cannot approve their own run


@pytest.mark.asyncio
async def test_validation_and_auth(client):
    assert (await client.get("/api/agents")).status_code == 401
    op = await login(client, "operator@acme.test")
    agent = (await client.get("/api/agents", headers=op)).json()[0]
    assert (await client.post(f"/api/agents/{agent['id']}/runs", json={"input": "x"}, headers=op)).status_code == 422
    r = await client.post("/api/agents", json={"name": "A", "allowed_actions": ["rm_rf"]}, headers=op)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_failed_run_retries_then_can_be_requeued(client, monkeypatch):
    calls = 0

    async def boom(*_):
        nonlocal calls
        calls += 1
        raise RuntimeError("connector down")

    op, approver = await login(client, "operator@acme.test"), await login(client, "approver@acme.test")
    run = await start(client, op)
    with monkeypatch.context() as m:
        m.setattr("ai_maneger.workflow.simulate_action", boom)
        await client.post(f"/api/runs/{run['id']}/decision", json={"decision": "approved"}, headers=approver)
        await service.drain()
    failed = (await client.get(f"/api/runs/{run['id']}", headers=op)).json()
    assert failed["status"] == "failed" and "connector down" in failed["error"] and calls == 2

    assert (await client.post(f"/api/runs/{run['id']}/retry", headers=op)).status_code == 202
    await service.drain()
    assert (await client.get(f"/api/runs/{run['id']}", headers=op)).json()["status"] == "completed"


@pytest.mark.asyncio
async def test_bedrock_failure_switches_to_langgraph_and_completes(client, bedrock, chat):
    bedrock.failures = [aws_error("AccessDeniedException")]
    op, approver = await login(client, "operator@acme.test"), await login(client, "approver@acme.test")
    run = await start(client, op)
    assert bedrock.calls == 1 and chat.calls == 2
    assert run["status"] == "awaiting_approval" and run["engine"] == "langgraph"
    assert run["fallback_reason"] == "Bedrock AccessDeniedException"
    assert run["analysis"]["summary"] == "Locked (fallback)"
    assert "engine_switching" in [e["type"] for e in run["events"]]
    assert "arn:aws" not in json.dumps(run)

    await client.post(f"/api/runs/{run['id']}/decision", json={"decision": "approved"}, headers=approver)
    await service.drain()
    done = (await client.get(f"/api/runs/{run['id']}", headers=op)).json()
    assert done["status"] == "completed" and done["engine"] == "langgraph"
    assert bedrock.calls == 1  # the approved action does not go back to Bedrock


@pytest.mark.asyncio
async def test_run_stays_on_bedrock_when_it_works(client, chat):
    run = await start(client, await login(client, "operator@acme.test"))
    assert run["engine"] == "bedrock" and run["fallback_reason"] is None and chat.calls == 0


@pytest.mark.asyncio
async def test_run_fails_when_both_engines_fail(client, bedrock, chat):
    bedrock.failures = [aws_error("AccessDeniedException")]
    chat.fail = True
    run = await start(client, await login(client, "operator@acme.test"))
    assert run["status"] == "failed" and "LangChain ConnectionError" in run["error"]


@pytest.mark.asyncio
async def test_retry_tries_bedrock_first_again(client, bedrock, chat):
    bedrock.failures = [aws_error("AccessDeniedException")]
    chat.fail = True
    op = await login(client, "operator@acme.test")
    run = await start(client, op)
    assert (await client.post(f"/api/runs/{run['id']}/retry", headers=op)).status_code == 202
    await service.drain()
    again = (await client.get(f"/api/runs/{run['id']}", headers=op)).json()
    assert again["engine"] == "bedrock" and again["status"] == "awaiting_approval"
    assert again["fallback_reason"] is None


@pytest.mark.asyncio
async def test_action_failure_never_switches_engine(client, monkeypatch, bedrock, chat):
    async def boom(*_):
        raise RuntimeError("connector down")

    monkeypatch.setattr("ai_maneger.workflow.simulate_action", boom)
    bedrock.action = "create_ticket"  # needs no approval, so it executes straight away
    run = await start(client, await login(client, "operator@acme.test"))
    assert run["status"] == "failed" and run["engine"] == "bedrock" and chat.calls == 0


@pytest.mark.asyncio
async def test_bedrock_throttle_recovers_with_retry(client, bedrock):
    bedrock.failures = [aws_error("ThrottlingException")]
    run = await start(client, await login(client, "operator@acme.test"))
    assert run["status"] == "awaiting_approval" and run["engine"] == "bedrock"


@pytest.mark.asyncio
async def test_disallowed_model_action_is_escalated(client, bedrock):
    bedrock.action = "delete_all_users"
    run = await start(client, await login(client, "operator@acme.test"))
    assert run["proposal"]["action"] == "escalate_to_human" and run["status"] == "completed"


@pytest.mark.asyncio
async def test_disabled_agent_refuses_runs(client):
    op = await login(client, "operator@acme.test")
    agent = (await client.get("/api/agents", headers=op)).json()[0]
    async with sessions()() as s:
        await s.execute(update(Agent).where(Agent.id == agent["id"]).values(enabled=False))
        await s.commit()
    r = await client.post(f"/api/agents/{agent['id']}/runs", json={"input": ISSUE}, headers=op)
    assert r.status_code == 409
    async with sessions()() as s:
        await s.execute(update(Agent).where(Agent.id == agent["id"]).values(enabled=True))
        await s.commit()


def test_guardrails():
    assert sanitise_action("delete_everything", ["unlock_account"]) == "escalate_to_human"
    assert sanitise_action("reset_password", ["unlock_account"]) == "escalate_to_human"
    assert needs_approval("unlock_account", "sensitive") and needs_approval("create_ticket", "always")
    assert not needs_approval("create_ticket", "sensitive")
