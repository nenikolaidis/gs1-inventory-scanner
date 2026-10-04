import { useState, type FormEvent } from "react";

import { api, errorMessage, type User } from "../api";
import { useAuth } from "../auth";
import { Field, Notice } from "../ui";

export default function Setup() {
  const { setUser } = useAuth();
  const [form, setForm] = useState({ username: "", display_name: "", password: "", repeat: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (form.password !== form.repeat) {
      setError("Passwords don't match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { repeat: _repeat, ...body } = form;
      setUser(await api.post<User>("/api/auth/setup", body));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [key]: e.target.value });

  return (
    <div className="center-screen">
      <form className="card auth-card" onSubmit={submit}>
        <img src="/favicon.svg" alt="" width={40} height={40} />
        <h1>Welcome to GS1 Scanner</h1>
        <p className="muted">Create the first administrator account to get started.</p>
        {error && <Notice kind="error">{error}</Notice>}
        <Field label="Username" autoCapitalize="none" value={form.username} onChange={set("username")} required autoFocus />
        <Field label="Your name" value={form.display_name} onChange={set("display_name")} />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          hint="At least 8 characters."
          value={form.password}
          onChange={set("password")}
          required
        />
        <Field
          label="Repeat password"
          type="password"
          autoComplete="new-password"
          value={form.repeat}
          onChange={set("repeat")}
          required
        />
        <button className="btn primary block" disabled={busy}>
          {busy ? "Creating…" : "Create administrator"}
        </button>
      </form>
    </div>
  );
}
