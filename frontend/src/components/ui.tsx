import { ReactNode } from "react";

const TONES: Record<string, string> = {
  idle: "neutral", completed: "good", approved: "good",
  busy: "info", queued: "info", running: "info", executing: "info", switching_engine: "warn",
  awaiting_approval: "warn", failed: "bad", rejected: "bad", stopped: "warn", ended: "neutral",
};

export function Badge({ value }: { value: string }) {
  const active = ["busy", "running", "executing", "queued", "switching_engine"].includes(value);
  return (
    <span className={`badge ${TONES[value] ?? "neutral"}`}>
      {active && <i className="pulse" />}{value.replaceAll("_", " ")}
    </span>
  );
}

export const Field = ({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) => (
  <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
);

export const Notice = ({ tone = "bad", children }: { tone?: string; children: ReactNode }) => (
  <p className={`notice ${tone}`} role="alert">{children}</p>
);

export const time = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
