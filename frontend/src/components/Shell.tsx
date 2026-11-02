"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { api, getToken, Run, setToken, Tenant, User } from "@/lib/api";
import { AuthContext, Perm, permsFor, useApi } from "@/lib/hooks";

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User>();
  const isLogin = path === "/login";

  useEffect(() => {
    if (isLogin) return;
    if (!getToken()) { router.replace("/login"); return; }
    api<User>("/auth/me").then(setUser).catch(() => router.replace("/login"));
  }, [isLogin, path, router]);

  const auth = useMemo(
    () => user && { user, can: (p: Perm) => permsFor(user.role).includes(p) },
    [user],
  );
  if (isLogin) return <>{children}</>;
  if (!auth) return <div className="center muted">Loading…</div>;

  return (
    <AuthContext.Provider value={auth}>
      <div className="layout">
        <Sidebar user={auth.user} path={path} onSignOut={() => { setToken(null); router.replace("/login"); }} />
        <main>{children}</main>
      </div>
    </AuthContext.Provider>
  );
}

function Sidebar({ user, path, onSignOut }: { user: User; path: string; onSignOut: () => void }) {
  const { data: tenant } = useApi<Tenant>("/tenant");
  const { data: pending } = useApi<Run[]>("/runs?status=awaiting_approval", 4000);
  const links: [string, string, number?][] = [
    ["/", "Agents"], ["/runs", "Runs"], ["/approvals", "Approvals", pending?.length], ["/org", "Organisation"],
  ];
  return (
    <nav className="side">
      <div className="brand"><b>Agent Platform</b><span>{tenant?.name ?? " "}</span></div>
      <div className="links">
        {links.map(([href, label, count]) => (
          <Link key={href} href={href} className={(href === "/" ? path === "/" || path.startsWith("/agents") : path.startsWith(href)) ? "on" : ""}>
            {label}{!!count && <em>{count}</em>}
          </Link>
        ))}
      </div>
      <div className="who">
        <span>{user.email}</span><small>{user.role}</small>
        <button className="link" onClick={onSignOut}>Sign out</button>
      </div>
    </nav>
  );
}
