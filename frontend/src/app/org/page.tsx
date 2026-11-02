"use client";
import { FormEvent, useEffect, useState } from "react";
import { Badge, Field, Notice, time } from "@/components/ui";
import { api, Role, RunEvent, Tenant, User } from "@/lib/api";
import { useApi, useAuth } from "@/lib/hooks";

const ROLES: Role[] = ["admin", "operator", "approver", "viewer"];
const BLANK = { name: "", email: "", password: "", role: "viewer" as Role };

export default function Org() {
  const { can } = useAuth();
  const admin = can("manage_tenant");
  const { data: tenant, reload: reloadTenant } = useApi<Tenant>("/tenant");
  const { data: members, reload } = useApi<User[]>("/tenant/members");
  const { data: audit } = useApi<RunEvent[]>(can("audit") ? "/audit?limit=50" : null, 5000);
  const [orgName, setOrgName] = useState("");
  const [member, setMember] = useState(BLANK);
  const [error, setError] = useState<string>();

  useEffect(() => { if (tenant) setOrgName(tenant.name); }, [tenant]);

  const guard = async (fn: () => Promise<unknown>) => {
    setError(undefined);
    try { await fn(); await reload(); } catch (e) { setError((e as Error).message); }
  };
  const rename = (e: FormEvent) => {
    e.preventDefault();
    guard(async () => { await api("/tenant", { method: "PATCH", body: { name: orgName } }); await reloadTenant(); });
  };
  const add = (e: FormEvent) => {
    e.preventDefault();
    guard(async () => { await api("/tenant/members", { body: member }); setMember(BLANK); });
  };
  const email = (id: string) => members?.find((m) => m.id === id)?.email ?? id;

  return (
    <>
      <div className="head"><div><h1>Organisation</h1><p>Members, roles and the audit log</p></div></div>
      {error && <Notice>{error}</Notice>}
      {admin && (
        <div className="panel">
          <h2>Details</h2>
          <form className="actions" onSubmit={rename}>
            <input style={{ maxWidth: 320 }} aria-label="Organisation name" required value={orgName} onChange={(e) => setOrgName(e.target.value)} />
            <button>Rename</button>
          </form>
        </div>
      )}
      <div className="panel">
        <h2>Members</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Role</th>{admin && <th />}</tr></thead>
            <tbody>
              {members?.map((m) => (
                <tr key={m.id}>
                  <td>{m.name}</td>
                  <td>{m.email}</td>
                  <td>
                    {admin ? (
                      <select aria-label={`Role for ${m.email}`} value={m.role} style={{ width: "auto", padding: "2px 6px" }}
                        onChange={(e) => guard(() => api(`/tenant/members/${m.id}`, { method: "PATCH", body: { role: e.target.value } }))}>
                        {ROLES.map((r) => <option key={r}>{r}</option>)}
                      </select>
                    ) : m.role}
                  </td>
                  {admin && <td><button className="small bad" onClick={() => guard(() => api(`/tenant/members/${m.id}`, { method: "DELETE" }))}>Remove</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {admin && (
        <div className="panel" style={{ maxWidth: 620 }}>
          <h2>Add member</h2>
          <form className="form" onSubmit={add}>
            <Field label="Name"><input required value={member.name} onChange={(e) => setMember({ ...member, name: e.target.value })} /></Field>
            <Field label="Email"><input required type="email" value={member.email} onChange={(e) => setMember({ ...member, email: e.target.value })} /></Field>
            <Field label="Temporary password"><input required type="password" minLength={8} value={member.password} onChange={(e) => setMember({ ...member, password: e.target.value })} /></Field>
            <Field label="Role">
              <select value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value as Role })}>
                {ROLES.map((r) => <option key={r}>{r}</option>)}
              </select>
            </Field>
            <div><button className="primary">Add member</button></div>
          </form>
        </div>
      )}
      {audit && (
        <div className="panel">
          <h2>Audit log</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Detail</th></tr></thead>
              <tbody>
                {audit.map((e) => (
                  <tr key={e.id}>
                    <td className="nowrap muted">{time(e.created_at)}</td>
                    <td className="nowrap">{e.type.replaceAll("_", " ")}</td>
                    <td className="nowrap">{email(e.actor)}</td>
                    <td className="clip">{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
