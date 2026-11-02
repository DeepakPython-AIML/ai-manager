"use client";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AgentForm } from "@/components/AgentForm";
import { RunsTable } from "@/components/RunsTable";
import { Badge, Field, Notice } from "@/components/ui";
import { Agent, api, Run } from "@/lib/api";
import { useApi, useAuth } from "@/lib/hooks";

export default function AgentPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { can } = useAuth();
  const { data: agent, error, reload } = useApi<Agent>(`/agents/${id}`);
  const { data: runs } = useApi<Run[]>(`/runs?agent_id=${id}&limit=20`, 3000);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [submitError, setSubmitError] = useState<string>();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setSubmitError(undefined);
    try {
      const run = await api<Run>(`/agents/${id}/runs`, { body: { input } });
      router.push(`/runs/${run.id}`);
    } catch (err) { setSubmitError((err as Error).message); setBusy(false); }
  }

  async function toggle() {
    await api(`/agents/${id}`, { method: "PATCH", body: { enabled: !agent?.enabled } });
    reload();
  }

  if (error) return <Notice>{error}</Notice>;
  if (!agent) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="head">
        <div>
          <h1>{agent.name}</h1>
          <p>{agent.description}</p>
          <p>Engines: Amazon Bedrock, then LangGraph + LangChain if it fails</p>
        </div>
        {can("manage_agents") && (
          <div className="actions">
            <button onClick={() => setEditing(!editing)}>{editing ? "Close" : "Configure"}</button>
            <button onClick={toggle}>{agent.enabled ? "Disable" : "Enable"}</button>
          </div>
        )}
      </div>
      {!agent.enabled && <div style={{ marginBottom: 12 }}><Badge value="disabled" /></div>}
      {editing && (
        <div className="panel" style={{ maxWidth: 620 }}>
          <AgentForm agent={agent} onSaved={() => { setEditing(false); reload(); }} />
        </div>
      )}
      {can("run") && (
        <div className="panel">
          <h2>New request</h2>
          {submitError && <Notice>{submitError}</Notice>}
          <form className="form" onSubmit={submit}>
            <Field label="Describe the issue">
              <textarea required minLength={5} maxLength={2000} placeholder="What do you need help with?" value={input} onChange={(e) => setInput(e.target.value)} />
            </Field>
            <div><button className="primary" disabled={busy || !agent.enabled}>{busy ? "Submitting…" : "Run agent"}</button></div>
          </form>
        </div>
      )}
      <div className="panel"><h2>Recent runs</h2><RunsTable runs={runs ?? []} /></div>
    </>
  );
}
