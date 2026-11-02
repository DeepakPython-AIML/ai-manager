"use client";
import Link from "next/link";
import { Decide } from "@/components/Decide";
import { Badge, Notice, time } from "@/components/ui";
import { Run } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export default function Approvals() {
  const { data, error, reload } = useApi<Run[]>("/runs?status=awaiting_approval", 3000);
  return (
    <>
      <div className="head"><div><h1>Approvals</h1><p>Agent actions waiting for a human decision</p></div></div>
      {error && <Notice>{error}</Notice>}
      {data?.length === 0 && <p className="muted">Nothing is waiting for approval.</p>}
      {data?.map((r) => (
        <div className="panel" key={r.id}>
          <div className="row" style={{ marginBottom: 8 }}>
            <b>{r.proposal?.action_label}</b>
            {r.analysis && <Badge value={r.analysis.severity} />}
          </div>
          <p>{r.input}</p>
          <p className="muted" style={{ margin: "6px 0 12px" }}>{r.proposal?.resolution}</p>
          <p style={{ marginBottom: 12, fontSize: 13 }} className="muted">
            Target: {r.proposal?.target} · {time(r.created_at)} · <Link href={`/runs/${r.id}`}>Full trace</Link>
          </p>
          <Decide run={r} onDone={reload} />
        </div>
      ))}
    </>
  );
}
