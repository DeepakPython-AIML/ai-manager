"use client";
import Link from "next/link";
import { AgentControls } from "@/components/AgentControls";
import { Badge, Notice } from "@/components/ui";
import { Agent, Run } from "@/lib/api";
import { useApi, useAuth } from "@/lib/hooks";

export default function Dashboard() {
  const { can } = useAuth();
  const { data: agents, error, reload } = useApi<Agent[]>("/agents", 3000);
  const { data: runs } = useApi<Run[]>("/runs?limit=200", 3000);
  const count = (s: string[]) => runs?.filter((r) => s.includes(r.status)).length ?? 0;
  const stats: [string, number][] = [
    ["Agents", agents?.length ?? 0],
    ["In progress", count(["queued", "running", "executing"])],
    ["Awaiting approval", count(["awaiting_approval"])],
    ["Completed", count(["completed"])],
    ["Failed", count(["failed"])],
  ];
  return (
    <>
      <div className="head">
        <div><h1>Agents</h1><p>Registered agents and what they are doing now</p></div>
        {can("manage_agents") && <Link className="btn primary" href="/agents/new">Register agent</Link>}
      </div>
      {error && <Notice>{error}</Notice>}
      <div className="stats">{stats.map(([label, n]) => <div className="stat" key={label}><b>{n}</b><span>{label}</span></div>)}</div>
      <div className="grid">
        {agents?.map((a) => (
          <div className="card" key={a.id}>
            <Link className="card-link" href={`/agents/${a.id}`}>
              <div className="row"><b>{a.name}</b><Badge value={a.status ?? "idle"} /></div>
              <p className="muted">{a.description || "No description"}</p>
              <small className="muted">{a.total_runs} runs · approval: {a.approval_policy}</small>
            </Link>
            <AgentControls agent={a} onChange={reload} />
          </div>
        ))}
      </div>
      {agents?.length === 0 && <p className="muted">No agents yet.</p>}
    </>
  );
}
