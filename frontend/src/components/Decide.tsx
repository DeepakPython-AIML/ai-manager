"use client";
import { useState } from "react";
import { api, Run } from "@/lib/api";
import { useAuth } from "@/lib/hooks";
import { Field, Notice } from "./ui";

export function Decide({ run, onDone }: { run: Run; onDone: () => void }) {
  const { can, user } = useAuth();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  if (!can("approve")) return <Notice tone="neutral">Waiting for someone with the approver role.</Notice>;

  async function decide(decision: "approved" | "rejected") {
    setBusy(true);
    setError(undefined);
    try {
      await api(`/runs/${run.id}/decision`, { body: { decision, note } });
      onDone();
    } catch (e) { setError((e as Error).message); setBusy(false); }
  }

  return (
    <div className="form">
      {error && <Notice>{error}</Notice>}
      {run.requested_by === user.id && (
        <Notice tone="neutral">You submitted this request. Your decision will be marked in the audit log.</Notice>
      )}
      <Field label="Note (optional)"><input maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      <div className="actions">
        <button className="good" disabled={busy} onClick={() => decide("approved")}>Approve and execute</button>
        <button className="bad" disabled={busy} onClick={() => decide("rejected")}>Reject</button>
      </div>
    </div>
  );
}
