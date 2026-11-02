"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Decide } from "@/components/Decide";
import { EngineSwitchModal } from "@/components/EngineSwitchModal";
import { Badge, Notice, time } from "@/components/ui";
import { ACTIVE, api, ENGINE_LABELS, Run } from "@/lib/api";
import { useApi, useAuth } from "@/lib/hooks";

const poll = (r: Run) => (ACTIVE.includes(r.status) ? 1000 : r.status === "awaiting_approval" ? 3000 : undefined);

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const { data: run, error, reload } = useApi<Run>(`/runs/${id}`, poll);
  const [retryError, setRetryError] = useState<string>();

  if (error && !run) return <Notice>{error}</Notice>;
  if (!run) return <p className="muted">Loading…</p>;

  async function retry() {
    try { await api(`/runs/${id}/retry`, { method: "POST" }); reload(); }
    catch (e) { setRetryError((e as Error).message); }
  }

  const { analysis: a, proposal: p, outcome: o } = run;
  return (
    <>
      <EngineSwitchModal active={run.status === "switching_engine"} reason={run.fallback_reason} />
      <div className="head">
        <div>
          <h1>Run {run.id.slice(0, 8)}</h1>
          <p><Link href={`/agents/${run.agent_id}`}>Back to agent</Link> · {time(run.created_at)}</p>
        </div>
        <Badge value={run.status} />
      </div>
      {run.fallback_reason && run.status !== "switching_engine" && (
        <Notice tone="warn">Amazon Bedrock failed ({run.fallback_reason}), so this run switched to LangGraph + LangChain.</Notice>
      )}
      <div className="split">
        <div>
          <div className="panel"><h2>Request</h2><p>{run.input}</p></div>

          {run.status === "awaiting_approval" && p && (
            <div className="panel"><h2>Approval required: {p.action_label}</h2><Decide run={run} onDone={reload} /></div>
          )}
          {run.status === "failed" && (
            <div className="panel">
              <h2>Failed after {run.attempts} attempts</h2>
              <Notice>{retryError ?? run.error}</Notice>
              {can("run") && <button onClick={retry}>Retry run</button>}
            </div>
          )}
          {run.status === "blocked" && <Notice>{run.error}</Notice>}
          {run.status === "rejected" && (
            <Notice tone="neutral">Rejected, so nothing was executed.{run.decision_note ? ` Note: ${run.decision_note}` : ""}</Notice>
          )}
          {o && (
            <div className="panel">
              <h2>Outcome</h2>
              <Notice tone="good">{o.detail}</Notice>
              <dl className="kv">
                <dt>Reference</dt><dd>{o.reference}</dd>
                <dt>Mode</dt><dd>{o.simulated ? "Simulated, no real system changed" : "Live"}</dd>
                {run.decision_note && <><dt>Approver note</dt><dd>{run.decision_note}</dd></>}
              </dl>
            </div>
          )}
          {a && (
            <div className="panel">
              <h2>Analysis</h2>
              <dl className="kv">
                <dt>Summary</dt><dd>{a.summary}</dd>
                <dt>Category</dt><dd>{a.category}</dd>
                <dt>Severity</dt><dd>{a.severity}</dd>
                <dt>System</dt><dd>{a.affected_system}</dd>
                <dt>Engine</dt><dd>{run.engine ? ENGINE_LABELS[run.engine] : "—"}</dd>
              </dl>
            </div>
          )}
          {p && (
            <div className="panel">
              <h2>Proposed resolution</h2>
              <dl className="kv">
                <dt>Action</dt><dd>{p.action_label}{p.sensitive ? " (sensitive)" : ""}</dd>
                <dt>Target</dt><dd>{p.target}</dd>
                <dt>Resolution</dt><dd>{p.resolution}</dd>
                <dt>Confidence</dt><dd>{Math.round(p.confidence * 100)}%</dd>
                <dt>Message to user</dt><dd>{p.user_message || "—"}</dd>
              </dl>
            </div>
          )}
        </div>
        <div className="panel">
          <h2>Trace</h2>
          <ol className="steps">
            {run.events?.map((e) => <li key={e.id}><time>{time(e.created_at)}</time>{e.message}</li>)}
          </ol>
        </div>
      </div>
    </>
  );
}
