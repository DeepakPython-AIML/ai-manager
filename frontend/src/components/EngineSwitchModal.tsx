"use client";
import { useEffect, useState } from "react";

const SECONDS = 3;

/** Shown for 3 seconds from the moment a run starts switching. It can't be dismissed. */
export function EngineSwitchModal({ active, reason }: { active: boolean; reason: string | null }) {
  const [left, setLeft] = useState(0);

  useEffect(() => {
    if (active) setLeft((s) => s || SECONDS);
  }, [active]);

  useEffect(() => {
    if (!left) return;
    const timer = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(timer);
  }, [left]);

  if (!left) return null;
  return (
    <div className="modal-back">
      <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="switch-title">
        <h2 id="switch-title">Switching to Groq</h2>
        <p className="muted">Amazon Bedrock is not available{reason ? ` (${reason})` : ""}. Your request will continue automatically.</p>
        <p>Switching in {left}s…</p>
        <div className="bar"><i /></div>
      </div>
    </div>
  );
}
