"use client";
import { useRouter } from "next/navigation";
import { AgentForm } from "@/components/AgentForm";

export default function NewAgent() {
  const router = useRouter();
  return (
    <>
      <div className="head"><div><h1>Register agent</h1><p>Configure its model, prompt and guardrails</p></div></div>
      <div className="panel" style={{ maxWidth: 620 }}><AgentForm onSaved={(a) => router.push(`/agents/${a.id}`)} /></div>
    </>
  );
}
