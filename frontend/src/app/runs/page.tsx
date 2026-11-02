"use client";
import { useState } from "react";
import { RunsTable } from "@/components/RunsTable";
import { Notice } from "@/components/ui";
import { Run } from "@/lib/api";
import { useApi } from "@/lib/hooks";

const FILTERS = ["all", "running", "awaiting_approval", "completed", "rejected", "failed"];

export default function Runs() {
  const [filter, setFilter] = useState("all");
  const { data, error } = useApi<Run[]>(filter === "all" ? "/runs?limit=100" : `/runs?limit=100&status=${filter}`, 3000);
  return (
    <>
      <div className="head"><div><h1>Runs</h1><p>Execution history across all agents</p></div></div>
      <div className="tabs">
        {FILTERS.map((f) => (
          <button key={f} className={f === filter ? "on" : ""} onClick={() => setFilter(f)}>{f.replaceAll("_", " ")}</button>
        ))}
      </div>
      {error && <Notice>{error}</Notice>}
      <div className="panel"><RunsTable runs={data ?? []} /></div>
    </>
  );
}
