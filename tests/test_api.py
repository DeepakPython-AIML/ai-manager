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
from ai_maneger.config import get_settings
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
async def test_rbac_and_self_decisions(client, monkeypatch):
    viewer, admin = await login(client, "viewer@acme.test"), await login(client, "admin@acme.test")
    agent = (await client.get("/api/agents", headers=viewer)).json()[0]
    r = await client.post(f"/api/agents/{agent['id']}/runs", json={"input": ISSUE}, headers=viewer)
    assert r.status_code == 403

    run = await start(client, admin)
    url = f"/api/runs/{run['id']}/decision"
    op = await login(client, "operator@acme.test")
    assert (await client.post(url, json={"decision": "approved"}, headers=op)).status_code == 403

    with monkeypatch.context() as m:  # strict mode enforces separation of duties
        m.setattr(get_settings(), "allow_self_approval", False)
        assert (await client.post(url, json={"decision": "approved"}, headers=admin)).status_code == 403

    assert (await client.post(url, json={"decision": "approved"}, headers=admin)).status_code == 200
    await service.drain()
    done = (await client.get(f"/api/runs/{run['id']}", headers=admin)).json()
    assert done["status"] == "completed"
    event = next(e for e in done["events"] if e["type"] == "approved")
    assert event["data"]["self_decision"] is True and "own request" in event["message"]


@pytest.mark.asyncio
async def test_admin_can_reject_own_request(client):
    admin = await login(client, "admin@acme.test")
    run = await start(client, admin)
    r = await client.post(f"/api/runs/{run['id']}/decision", json={"decision": "rejected"}, headers=admin)
    assert r.status_code == 200
    await service.drain()
    done = (await client.get(f"/api/runs/{run['id']}", headers=admin)).json()
    assert done["status"] == "rejected" and done["outcome"] is None


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


async def new_agent(c, headers, name):
    # Globex only: agents here stay stopped or ended, which must not affect the Acme tests.
    r = await c.post("/api/agents", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def status_of(c, headers, agent):
    agents = (await c.get("/api/agents", headers=headers)).json()
    return next(a["status"] for a in agents if a["id"] == agent["id"])


async def agent_run(c, headers, agent):
    return await c.post(f"/api/agents/{agent['id']}/runs", json={"input": ISSUE}, headers=headers)


@pytest.mark.asyncio
async def test_stopped_agent_refuses_runs_until_started(client):
    admin = await login(client, "admin@globex.test")
    agent = await new_agent(client, admin, "Stoppable")
    url = f"/api/agents/{agent['id']}"
    assert (await client.post(f"{url}/stop", headers=admin)).status_code == 200
    assert await status_of(client, admin, agent) == "stopped"
    assert (await agent_run(client, admin, agent)).status_code == 409
    assert (await client.post(f"{url}/start", headers=admin)).status_code == 200
    assert await status_of(client, admin, agent) == "idle"
    assert (await agent_run(client, admin, agent)).status_code == 202
    await service.drain()


@pytest.mark.asyncio
async def test_ended_agent_is_kept_and_cannot_come_back(client):
    admin = await login(client, "admin@globex.test")
    agent = await new_agent(client, admin, "Endable")
    url = f"/api/agents/{agent['id']}"
    assert (await client.post(f"{url}/end", headers=admin)).status_code == 200
    assert await status_of(client, admin, agent) == "ended"
    assert (await client.get(url, headers=admin)).json()["ended_at"]
    for call in (client.post(f"{url}/start", headers=admin), client.post(f"{url}/stop", headers=admin),
                 client.post(f"{url}/end", headers=admin), client.patch(url, json={"name": "x"}, headers=admin),
                 agent_run(client, admin, agent)):
        assert (await call).status_code == 409


@pytest.mark.asyncio
async def test_stop_blocks_approval_but_not_rejection(client):
    admin = await login(client, "admin@globex.test")
    agent = await new_agent(client, admin, "Paused")
    run_id = (await agent_run(client, admin, agent)).json()["id"]
    await service.drain()
    await client.post(f"/api/agents/{agent['id']}/stop", headers=admin)
    url = f"/api/runs/{run_id}/decision"
    assert (await client.post(url, json={"decision": "approved"}, headers=admin)).status_code == 409
    assert (await client.post(url, json={"decision": "rejected"}, headers=admin)).status_code == 200


@pytest.mark.asyncio
async def test_ending_agent_rejects_pending_approvals(client):
    admin = await login(client, "admin@globex.test")
    agent = await new_agent(client, admin, "Pending")
    run_id = (await agent_run(client, admin, agent)).json()["id"]
    await service.drain()
    await client.post(f"/api/agents/{agent['id']}/end", headers=admin)
    run = (await client.get(f"/api/runs/{run_id}", headers=admin)).json()
    assert run["status"] == "rejected" and run["decision_note"] == "Agent was ended" and run["outcome"] is None


@pytest.mark.asyncio
async def test_action_does_not_run_if_agent_stopped_mid_run(client, bedrock):
    admin = await login(client, "admin@globex.test")
    agent = await new_agent(client, admin, "Racing")
    bedrock.action = "create_ticket"  # needs no approval, so only the guard can stop it
    r = await agent_run(client, admin, agent)
    await client.post(f"/api/agents/{agent['id']}/stop", headers=admin)
    await service.drain()
    run = (await client.get(f"/api/runs/{r.json()['id']}", headers=admin)).json()
    assert run["status"] == "failed" and "stopped" in run["error"] and run["outcome"] is None


@pytest.mark.asyncio
async def test_only_agent_managers_can_stop_or_end(client):
    admin, viewer = await login(client, "admin@globex.test"), await login(client, "viewer@globex.test")
    agent = await new_agent(client, admin, "Guarded")
    for action in ("stop", "start", "end"):
        assert (await client.post(f"/api/agents/{agent['id']}/{action}", headers=viewer)).status_code == 403


def test_guardrails():
    assert sanitise_action("delete_everything", ["unlock_account"]) == "escalate_to_human"
    assert sanitise_action("reset_password", ["unlock_account"]) == "escalate_to_human"
    assert needs_approval("unlock_account", "sensitive") and needs_approval("create_ticket", "always")
    assert not needs_approval("create_ticket", "sensitive")
