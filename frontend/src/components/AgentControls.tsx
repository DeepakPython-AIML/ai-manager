"use client";
import { useState } from "react";
import { Agent, api } from "@/lib/api";
import { useAuth } from "@/lib/hooks";
import { Notice } from "./ui";

export function AgentControls({ agent, onChange }: { agent: Agent; onChange: () => void }) {
  const { can } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  if (!can("manage_agents") || agent.ended_at) return null;

  async function run(action: "start" | "stop" | "end") {
    setBusy(true);
    setError(undefined);
    try {
      await api(`/agents/${agent.id}/${action}`, { method: "POST" });
      onChange();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  function end() {
    const message = `End ${agent.name}? This can't be undone. Anything awaiting approval will be rejected. Its history is kept.`;
    if (window.confirm(message)) run("end");
  }

  return (
    <div className="actions">
      {error && <Notice>{error}</Notice>}
      {agent.enabled
        ? <button className="small" disabled={busy} onClick={() => run("stop")}>Stop</button>
        : <button className="small" disabled={busy} onClick={() => run("start")}>Start</button>}
      <button className="small bad" disabled={busy} onClick={end}>End agent</button>
    </div>
  );
}
