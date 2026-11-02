"use client";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api, setToken, User } from "@/lib/api";
import { Field, Notice } from "@/components/ui";

const DEMO = ["admin", "operator", "approver", "viewer"];

export default function Login() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [form, setForm] = useState({ org_name: "", name: "", email: "", password: "" });
  const [error, setError] = useState<string>();
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function auth(path: string, body: object) {
    setError(undefined);
    try {
      const { access_token } = await api<{ access_token: string; user: User }>(path, { body });
      setToken(access_token);
      router.replace("/");
    } catch (e) { setError((e as Error).message); }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    auth(mode === "login" ? "/auth/login" : "/auth/signup",
      mode === "login" ? { email: form.email, password: form.password } : form);
  };

  return (
    <div className="center">
      <div className="auth">
        <div className="panel">
          <h1 style={{ marginBottom: 16 }}>{mode === "login" ? "Sign in" : "Create organisation"}</h1>
          {error && <Notice>{error}</Notice>}
          <form className="form" onSubmit={submit}>
            {mode === "signup" && <>
              <Field label="Organisation"><input required value={form.org_name} onChange={set("org_name")} /></Field>
              <Field label="Your name"><input required value={form.name} onChange={set("name")} /></Field>
            </>}
            <Field label="Email"><input required type="email" autoComplete="email" value={form.email} onChange={set("email")} /></Field>
            <Field label="Password" hint={mode === "signup" ? "At least 8 characters" : undefined}>
              <input required type="password" minLength={mode === "signup" ? 8 : undefined} value={form.password} onChange={set("password")} />
            </Field>
            <button className="primary">{mode === "login" ? "Sign in" : "Create organisation"}</button>
          </form>
          <p style={{ marginTop: 12 }}>
            <button className="link" onClick={() => setMode(mode === "login" ? "signup" : "login")}>
              {mode === "login" ? "New here? Create an organisation" : "Have an account? Sign in"}
            </button>
          </p>
        </div>
        <div className="panel">
          <h2>Demo accounts: Acme Corp</h2>
          <div className="demo">
            {DEMO.map((r) => (
              <button key={r} className="small" onClick={() => auth("/auth/login", { email: `${r}@acme.test`, password: "demo1234" })}>
                {r[0].toUpperCase() + r.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
