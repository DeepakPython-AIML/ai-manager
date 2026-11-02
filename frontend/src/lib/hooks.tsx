"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, User } from "./api";

export const AuthContext = createContext<{ user: User; can: (p: Perm) => boolean } | null>(null);
export type Perm = "run" | "approve" | "manage_agents" | "manage_tenant" | "audit";

const PERMS: Record<User["role"], Perm[]> = {
  admin: ["run", "approve", "manage_agents", "manage_tenant", "audit"],
  operator: ["run", "manage_agents"],
  approver: ["approve", "audit"],
  viewer: [],
};
export const permsFor = (role: User["role"]) => PERMS[role];

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthContext");
  return ctx;
}

/** Fetch a path, optionally re-fetching every `intervalMs`. Null path means "skip". */
export function useApi<T>(path: string | null, intervalMs?: number | ((data: T) => number | undefined)) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<string>();
  const dataRef = useRef<T>(undefined);

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const next = await api<T>(path);
      dataRef.current = next;
      setData(next);
      setError(undefined);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [path]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const tick = async () => {
      await load();
      const ms = typeof intervalMs === "function"
        ? dataRef.current !== undefined ? intervalMs(dataRef.current) : undefined
        : intervalMs;
      if (ms && !stopped) timer = setTimeout(tick, ms);
    };
    tick();
    return () => { stopped = true; clearTimeout(timer); };
  }, [load, intervalMs]);

  return { data, error, reload: load };
}
