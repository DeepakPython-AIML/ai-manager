"use client";
import { useRouter } from "next/navigation";
import { ENGINE_LABELS, Run } from "@/lib/api";
import { Badge, time } from "./ui";

export function RunsTable({ runs }: { runs: Run[] }) {
  const router = useRouter();
  if (!runs.length) return <p className="muted">No runs yet.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Request</th><th>Status</th><th>Action</th><th>Engine</th><th>Started</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="link-row" onClick={() => router.push(`/runs/${r.id}`)}>
              <td className="clip"><a href={`/runs/${r.id}`} onClick={(e) => e.preventDefault()}>{r.input}</a></td>
              <td><Badge value={r.status} /></td>
              <td className="nowrap">{r.proposal?.action_label ?? "—"}</td>
              <td className="nowrap">{r.engine ? ENGINE_LABELS[r.engine] : "—"}</td>
              <td className="nowrap muted">{time(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
