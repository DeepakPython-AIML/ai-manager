export type Role = "admin" | "operator" | "approver" | "viewer";
export type User = { id: string; tenant_id: string; email: string; name: string; role: Role };
export type Tenant = { id: string; name: string; created_at: string };
export type EngineInfo = { id: string; label: string; role: string; default_model: string };
export type Action = { id: string; label: string; sensitive: boolean };
export type Agent = {
  id: string; name: string; description: string; kind: string; model_id: string | null;
  fallback_model_id: string | null;
  system_prompt: string; approval_policy: "sensitive" | "always"; allowed_actions: string[];
  enabled: boolean; ended_at: string | null; created_at: string; total_runs?: number;
  status?: "idle" | "busy" | "awaiting_approval" | "stopped" | "ended";
};
export type RunStatus = "queued" | "running" | "switching_engine" | "awaiting_approval" | "executing" | "completed" | "rejected" | "blocked" | "failed";
export type RunEvent = {
  id: string; run_id: string | null; type: string; actor: string; message: string;
  data: Record<string, unknown> | null; created_at: string;
};
export type Run = {
  id: string; agent_id: string; requested_by: string; input: string; status: RunStatus;
  engine: string | null; fallback_reason: string | null;
  analysis: { category: string; severity: string; summary: string; affected_system: string } | null;
  proposal: {
    action: string; action_label: string; resolution: string; target: string; confidence: number;
    user_message: string; sensitive: boolean; requires_approval: boolean;
  } | null;
  outcome: { reference: string; detail: string; simulated: boolean } | null;
  decision: string | null; decided_by: string | null; decision_note: string | null; decided_at: string | null;
  error: string | null; attempts: number; created_at: string; updated_at: string; events?: RunEvent[];
};

export const ACTIVE: RunStatus[] = ["queued", "running", "switching_engine", "executing"];
export const ENGINE_LABELS: Record<string, string> = { bedrock: "Amazon Bedrock", groq: "Groq", langgraph: "LangGraph + LangChain" };
const TOKEN_KEY = "agent-platform-token";

export const getToken = () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY));
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T = unknown>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const token = getToken();
  const res = await fetch(`/api${path}`, {
    method: init?.method ?? (init?.body ? "POST" : "GET"),
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: init?.body ? JSON.stringify(init.body) : undefined,
  });
  if (res.status === 401 && token) {
    setToken(null);
    window.location.href = "/login";
  }
  if (!res.ok) {
    const detail = await res.json().then((b) => b.detail).catch(() => null);
    const message = Array.isArray(detail)
      ? detail.map((d) => `${d.loc?.at(-1)}: ${d.msg}`).join("; ")
      : detail ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}
