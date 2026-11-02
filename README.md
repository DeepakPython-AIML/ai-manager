# AI Agent Management Platform

A small multi-tenant platform for registering AI agents, running them, watching what they do and
approving their actions before they execute. It includes an IT Support Agent built on Strands Agents with two engines:
Amazon Bedrock runs first, and Groq takes over if Bedrock fails. Both have guardrails on every model call. Every action it takes is simulated; no real account is changed.

**Stack:** Next.js 16, React 19, TypeScript · Python 3.14, FastAPI, SQLAlchemy · Amazon Bedrock
(Converse API, Guardrails) · Strands Agents · Groq · SQLite locally, PostgreSQL on AWS

## Contents

- [Run the app with aimanager](#run-the-app-with-aimanager)
- [Snapshots](#snapshots)
- [Current status](#current-status)
- [Stop or end an agent](#stop-or-end-an-agent)
- [How the two engines work](#how-the-two-engines-work)
- [Guardrails](#guardrails)
- [Architecture](#architecture)
- [Security and reliability](#security-and-reliability)
- [Summary](#summary)

## Run the app with aimanager

`aimanager` is the script in the project root that sets up, starts and stops everything.

Prerequisites: [uv](https://docs.astral.sh/uv/) and Node 20+. Add AWS credentials for Bedrock and
`GROQ_API_KEY` for the fallback.

```bash
cp .env.example .env   # add your AWS keys and GROQ_API_KEY
uv run python -m ai_maneger.bedrock_guardrail   # add the two lines it prints to .env
./aimanager --start
```

Without the guardrail settings the app still runs, but Bedrock refuses to call a model and every run goes to
the Groq engine.

| Command | What it does |
| --- | --- |
| `./aimanager --start` | Installs dependencies, then starts the backend and frontend in the background |
| `./aimanager --stop` | Stops the backend and frontend |
| `./aimanager --restart` | Stops everything, then starts it again |

`--start` is safe to run twice: anything already running is left alone. Logs are in `.run/backend.log` and
`.run/frontend.log`. Use `BACKEND_PORT` and `FRONTEND_PORT` to change the default ports, 8000 and 3000.

To run `aimanager` from any directory, link it into a folder on your `PATH`:

```bash
ln -s "$PWD/aimanager" /usr/local/bin/aimanager
```

Open http://localhost:3000. Demo accounts are on the sign-in page, and all use the password `demo1234`.
They exist for both Acme Corp (`@acme.test`) and Globex Inc (`@globex.test`).

Tests need no AWS access: `uv run pytest`. API docs are at http://localhost:8000/docs.

### Demo walkthrough

1. Sign in as **Operator**, open IT Support Agent, type a request and click **Run agent**. For example:
   "My account is locked after too many sign-in attempts."
2. Watch the run trace update live. If Bedrock is unavailable, the switching dialog appears for 3 seconds.
3. Sign out, sign in as **Approver** or **Admin**, and open **Approvals**. Only these two roles see the
   **Approve and execute** and **Reject** buttons.
4. Approve or reject. An approved run executes the simulated action and records its reference.
5. Sign in as **Admin** and open **Organisation** to manage members and read the audit log.

Sensitive actions such as unlocking an account wait for approval. Others, such as creating a ticket,
complete on their own.

## Snapshots

### Sign in

Sign in, create an organisation, or use a one-click demo account.

![Sign in](snapshots/fullpage_snapshot_localhost_2026-11-02-03-59-47.png)

### Agent dashboard

Registered agents, their status and run totals. This was taken before the fallback was added, so its two runs show as failed.

![Agent dashboard](snapshots/fullpage_snapshot_localhost_2026-11-02-04-00-09.png)

### Register an agent

Both engines are set up on every agent, with the model, prompt, approval policy and allowed actions.

![Register an agent](snapshots/fullpage_snapshot_localhost_2026-11-02-04-18-20.png)

### Submit a request

Type a request for the agent and see its engine order and recent runs.

![Submit a request](snapshots/fullpage_snapshot_localhost_2026-11-02-04-19-24.png)

### Run switched engine

Bedrock failed, so the run continued on the fallback and completed. The banner and trace show why it switched. This was taken when the fallback used LangGraph; it now shows Groq.

![Run switched engine](snapshots/fullpage_snapshot_localhost_2026-11-02-04-19-53.png)

### Run history

Filter runs by status. This was taken before the fallback was added; newer versions also have an Engine column.

![Run history](snapshots/fullpage_snapshot_localhost_2026-11-02-04-00-35.png)

### Approvals

The queue of actions waiting for a human decision.

![Approvals](snapshots/fullpage_snapshot_localhost_2026-11-02-04-00-52.png)

### Organisation and audit log

Manage members and roles, and read the audit log.

![Organisation and audit log](snapshots/fullpage_snapshot_localhost_2026-11-02-04-01-12.png)

### Failed run

A failed run shows its reason and full trace, with a **Retry run** button. This was taken before the fallback was added, when a Bedrock failure ended the run.

![Failed run](snapshots/fullpage_snapshot_localhost_2026-11-02-04-01-34.png)

## Current status

| Area | State |
| --- | --- |
| API, RBAC, tenant isolation, approvals, retries, engine switching, guardrails | Covered by 38 passing tests, with both engines stubbed |
| Frontend | Tested end to end in a real browser, including the switching dialog and approval |
| Groq engine on Strands | **Working.** Real model calls, tested through the API and in the browser |
| Amazon Bedrock engine on Strands | **Blocked.** The AWS account is not authorised to call models (see below), so every run currently switches to Groq |
| Bedrock Guardrail | **Created and tested** with `ApplyGuardrail` on 25 sample requests. Not yet tested on a real model reply through `Converse`, because of the block below |
| Strands guardrail middleware | **Working.** Tested with real Groq calls and in the browser |
| PostgreSQL, Cognito mode | Implemented but not yet run |

## Stop or end an agent

Admins and operators can do this from the dashboard or an agent's page. Agents are never deleted, so their
runs and audit history stay available.

| Action | Status | Can be undone | Effect |
| --- | --- | --- | --- |
| **Stop** | `stopped` | Yes, with **Start** | Refuses new runs, approvals and retries. Pending requests stay in Approvals and can still be rejected, or approved after **Start** |
| **End agent** | `ended` | No | Permanently retires the agent, stops its settings being changed, and rejects anything awaiting approval |

A run already in progress can finish its analysis, but its action will not execute once the agent is stopped
or ended; it is marked `failed` with that reason.

The API endpoints are `POST /api/agents/{id}/stop`, `/start` and `/end`.

## How the two engines work

Every agent has both engines ready. You can set a model for each when registering it, or leave them blank
to use the platform defaults.

1. Every new run tries **Amazon Bedrock** first. This includes re-runs from the **Retry run** button.
2. If Bedrock fails, the run changes to `switching_engine`, and the run page shows a 3-second dialog:
   "Switching to Groq".
3. The run then continues on **Groq**, and the page shows which engine was used and why.
4. If both engines fail, the run is marked `failed`.

Only model failures cause a switch. If an action itself fails, the engine is not changed, so an action is
never repeated on the other engine. An approved action runs on the engine that proposed it. A guardrail block
is not a failure and never causes a switch.

Both engines are [Strands Agents](https://strandsagents.com) and only the model differs. Bedrock uses
`BedrockModel`. The fallback uses `OpenAIModel` pointed at Groq's API with `GROQ_API_KEY`, which keeps it
working when AWS is the problem. Each model call is a new agent with no tools, so the model can only propose;
the platform decides what runs. **On the fallback, request text is sent to
Groq, outside AWS.** Without `GROQ_API_KEY`, a Bedrock failure ends the run as `failed`.

The code is kept separate:

| File | Purpose |
| --- | --- |
| `src/ai_maneger/engines/strands_engine.py` | Both engines: Strands agents on Bedrock and Groq |
| `src/ai_maneger/engines/guardrail_middleware.py` | Strands middleware: enforces Bedrock blocks and applies the Groq rules |
| `src/ai_maneger/bedrock_guardrail.py` | Bedrock Guardrail policy and the command that creates it |
| `src/ai_maneger/engines/__init__.py` | Engine registry and the order they are tried in |
| `src/ai_maneger/workflow.py` | Shared actions, prompts, guardrails and agent steps |
| `src/ai_maneger/service.py` | Runs engines in the background and handles the switch |

### AWS access check (2026-11-02)

| Capability | Result |
| --- | --- |
| Credentials (STS) | Valid |
| Bedrock: list models and inference profiles | Allowed |
| Bedrock: call a model (`Converse`) | **Refused** with `ValidationException: Operation not allowed` |
| AgentCore: list runtimes, memories and gateways | Allowed; the account has none in `us-east-1` or `us-west-2` |
| AgentCore: create or invoke | Not tested; creating resources was not attempted |

Model calls were refused for Amazon, Anthropic, Meta, OpenAI and other providers, in both `us-east-1` and
`us-west-2`. For the three models checked, `GetFoundationModelAvailability` reports
`authorizationStatus: NOT_AUTHORIZED` while agreement, entitlement and region are all `AVAILABLE`. The model
access use-case form has also not been filled out for this account.

To clear it, the account owner should complete the model access form in the Bedrock console. If calls are
still refused, check the account's billing status or open an AWS Support case. Runs that failed can then be
re-run with the **Retry run** button.

AgentCore is not used by this code yet.

## Guardrails

Every model call is checked in both directions, the request before it and the reply after it. Each engine
has its own guardrail:

| | Bedrock flow | Groq flow |
| --- | --- | --- |
| Guardrail | Amazon Bedrock Guardrails, passed on every `Converse` call | Strands middleware on `InvokeModelStage` |
| How it decides | AWS classifiers | Fixed rules, run in this process |
| Harmful content | Hate, insults, sexual content, violence, misconduct | Not covered |
| Prompt attacks | `PROMPT_ATTACK` filter on the request | Known injection phrases, and a check that replies don't leak the prompt |
| Blocked topics | Security control removal, credential theft | Bypass phrases, credential theft phrases |
| Sensitive data | Passwords, AWS keys, card numbers, US SSNs | Passwords, AWS access keys, private keys, card numbers, US SSNs |

- **A block is final.** The run ends as `blocked` with no retry and no engine switch, because switching would
  send the blocked text to the other model. Nothing executes, and **Retry run** is not offered.
- **The Bedrock flow fails closed.** With no guardrail configured, it makes no model call and the run moves to
  the Groq engine, which has its own checks.
- **Blocks are audited.** A `guardrail_blocked` event records the engine and policy names, but never the
  matched text. Each passed call adds a `guardrail_passed` event to the trace.
- **The agent's own prompt isn't checked on Bedrock.** Only the untrusted request is sent as `guardContent`,
  so the instructions in the prompt can't trigger a block. Replies are always checked.

Guardrails are one layer. The action allowlist and human approval still apply to anything that gets through,
and the Groq rules are simple patterns that reworded text can avoid. A blocked request stays in run
history as it was typed, so a pasted secret is kept there.

To change the Bedrock policy, edit `src/ai_maneger/bedrock_guardrail.py`, run
`uv run python -m ai_maneger.bedrock_guardrail` again, and set `BEDROCK_GUARDRAIL_VERSION` to the new version.
Test any change against normal support requests: an earlier wording of the policy blocked "the MFA prompt
never arrives".

## Architecture

![Architecture diagram](docs/architecture.png)

The repo today runs the API and worker in one process, with `asyncio` tasks in place of SQS. `service.spawn()`
is the only line that would change.

### Agent workflow

![Agent workflow diagram](docs/agent-workflow.png)

Diagram sources are in [docs/architecture.mmd](docs/architecture.mmd) and [docs/agent-workflow.mmd](docs/agent-workflow.mmd).

### Key decisions

- **Approval is a durable stop, not a paused process.** The graph ends and the run is saved as
  `awaiting_approval`, so an approval can arrive days later or after a restart.
- **The model only proposes.** Its output is schema-validated, its action must be on the agent's allowlist
  (anything else escalates to a human), and the code decides whether approval is needed.
- **A guardrail block ends the run.** A policy decision is not a model failure, so the fallback can't be used
  to get around it.
- **Fallback is always visible.** A switch is shown to the user, saved on the run and written to the audit
  log, so approvers can see which engine produced a proposal. If both engines fail, the run is `failed`.
- **Status changes use compare-and-swap,** so two approvers clicking together can't execute an action twice.

## Security and reliability

| Concern | This repo | Production |
| --- | --- | --- |
| Authentication | JWT login with scrypt-hashed passwords. `AUTH_MODE=cognito` verifies Cognito tokens via JWKS | Cognito with SAML/OIDC SSO and MFA |
| Authorisation | Server-side permission matrix: admin, operator, approver, viewer | Same, with roles from Cognito groups |
| Tenant isolation | Tenant comes from the verified token, never the request. Every query is scoped, and other tenants' rows return 404 | Add PostgreSQL row-level security |
| Human approval | Sensitive actions always need approval, and policy can only tighten this. Admins can decide on their own requests, and each such decision is marked in the audit log. Set `ALLOW_SELF_APPROVAL=false` to block this | Run with `ALLOW_SELF_APPROVAL=false`, and add approval expiry and multi-step approval |
| Failed runs | Model calls retry on transient errors, then the run switches engine. Action failures retry with backoff. Failed runs can be re-run, and in-flight runs resume on startup | SQS with a dead-letter queue, plus idempotency keys on real connectors |
| Audit and tracing | Append-only event log per run and tenant; request ids on every response | Export to S3 Object Lock; CloudWatch, X-Ray and Bedrock invocation logging |
| Secrets | `.env` is git-ignored, keys are `SecretStr`, and tenants see only Bedrock error codes, not ARNs | Task roles and Secrets Manager, with no long-lived keys |
| Prompt injection and unsafe content | User text is delimited and treated as data. Bedrock Guardrails or Strands middleware check each model call, and the allowlist and approval gate limit the damage | Keep traffic on Bedrock, or put an in-AWS model and the same guardrail behind the fallback. Redact secrets from stored requests |

### Supporting multiple customers securely

1. **Identity:** one Cognito user pool per environment, with `custom:tenant_id` writable only by admins and
   one federated identity provider per customer.
2. **Data:** a shared schema protected by row-level security, using a per-request `app.tenant_id` setting as a
   second line of defence behind the application's query scoping.
3. **Higher-tier isolation:** regulated customers get a dedicated database or AWS account, routed by tenant.
4. **Fair use:** per-tenant API Gateway usage plans, run quotas and Bedrock spend attribution.
5. **Encryption and audit:** per-tenant KMS keys for sensitive fields, and tenant-partitioned audit exports.

## Summary

**Completed:** the web app, REST API, IT Support Agent, Bedrock engine with Groq fallback on Strands Agents, guardrails on
both, async execution, persistent history, approvals, retries, validation, tenant and role management, audit
log and tests.

**Remaining:**
- Clear the AWS model access block and test the Bedrock engine and its guardrail against real models.
- Decide whether to host the agent on Bedrock AgentCore Runtime.
- Run against PostgreSQL and a real Cognito user pool.
- Write infrastructure as code and deploy to a test environment.

**Would improve for production:**
- Replace the Groq fallback with an in-AWS option if data must stay inside AWS.
- Move execution to SQS workers.
- Add Alembic migrations, in place of `create_all` on startup.
- Add PostgreSQL row-level security.
- Rate-limit login and move tokens out of `localStorage`.
- Push live updates over SSE or WebSockets instead of polling.
- Add frontend end-to-end tests and a model evaluation suite.
