"use client";
import { FormEvent, useState } from "react";
import { Action, Agent, api, EngineInfo } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Field, Notice } from "./ui";

export function AgentForm({ agent, onSaved }: { agent?: Agent; onSaved: (a: Agent) => void }) {
  const { data: actions } = useApi<Action[]>("/actions");
  const { data: engines } = useApi<EngineInfo[]>("/engines");
  const [form, setForm] = useState({
    name: agent?.name ?? "",
    description: agent?.description ?? "",
    model_id: agent?.model_id ?? "",
    fallback_model_id: agent?.fallback_model_id ?? "",
    system_prompt: agent?.system_prompt ?? "You are the corporate IT Support Agent. Prefer the least privileged fix.",
    approval_policy: agent?.approval_policy ?? "sensitive",
  });
  const [picked, setPicked] = useState<string[] | undefined>(agent?.allowed_actions);
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const allowed = picked ?? actions?.map((a) => a.id) ?? [];
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(undefined);
    try {
      const body = { ...form, model_id: form.model_id.trim() || null,
        fallback_model_id: form.fallback_model_id.trim() || null, allowed_actions: allowed };
      onSaved(await api<Agent>(agent ? `/agents/${agent.id}` : "/agents", { method: agent ? "PATCH" : "POST", body }));
    } catch (err) { setError((err as Error).message); } finally { setSaving(false); }
  }

  return (
    <form className="form" onSubmit={submit}>
      {error && <Notice>{error}</Notice>}
      <Field label="Name"><input required maxLength={120} value={form.name} onChange={set("name")} /></Field>
      <Field label="Description"><input maxLength={1000} value={form.description} onChange={set("description")} /></Field>
      <fieldset className="engines">
        <legend>Execution engines</legend>
        <p className="muted">Both are ready on every agent. Bedrock runs first; if it fails, the run switches to Groq.</p>
        <Field label="1. Amazon Bedrock model (primary)" hint="Leave blank for the platform default">
          <input maxLength={200} placeholder={engines?.[0]?.default_model} value={form.model_id} onChange={set("model_id")} />
        </Field>
        <Field label="2. Groq model (fallback)" hint="Leave blank for the platform default">
          <input maxLength={200} placeholder={engines?.[1]?.default_model} value={form.fallback_model_id} onChange={set("fallback_model_id")} />
        </Field>
      </fieldset>
      <Field label="System prompt"><textarea maxLength={4000} value={form.system_prompt} onChange={set("system_prompt")} /></Field>
      <Field label="Approval policy" hint="Sensitive actions always need approval, under either policy">
        <select value={form.approval_policy} onChange={set("approval_policy")}>
          <option value="sensitive">Sensitive actions only</option>
          <option value="always">Every action</option>
        </select>
      </Field>
      <fieldset style={{ border: 0, padding: 0, margin: 0 }} className="form">
        <legend style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>Allowed actions</legend>
        <div style={{ display: "grid", gap: 4 }}>
          {actions?.map((a) => (
            <label className="check" key={a.id}>
              <input type="checkbox" checked={allowed.includes(a.id)}
                onChange={(e) => setPicked(e.target.checked ? [...allowed, a.id] : allowed.filter((x) => x !== a.id))} />
              {a.label}{a.sensitive && <small className="muted">sensitive</small>}
            </label>
          ))}
        </div>
      </fieldset>
      <div><button className="primary" disabled={saving || !allowed.length}>{agent ? "Save changes" : "Register agent"}</button></div>
    </form>
  );
}
