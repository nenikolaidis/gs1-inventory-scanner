import { useState, type FormEvent } from "react";

import { api, errorMessage } from "../api";
import { useAuth, useUser } from "../auth";
import { Field, Notice, PageHeader } from "../ui";

export default function Account() {
  const user = useUser();
  const { logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function changePassword(e: FormEvent) {
    e.preventDefault();
    if (next !== repeat) {
      setMessage({ kind: "error", text: "New passwords don't match." });
      return;
    }
    try {
      await api.post("/api/auth/password", { current_password: current, new_password: next });
      setCurrent("");
      setNext("");
      setRepeat("");
      setMessage({ kind: "ok", text: "Password changed. Other devices have been logged out." });
    } catch (err) {
      setMessage({ kind: "error", text: errorMessage(err) });
    }
  }

  return (
    <>
      <PageHeader
        title="Account"
        actions={
          <button className="btn" onClick={logout}>
            Log out
          </button>
        }
      />
      <div className="card">
        <p>
          Logged in as <strong>{user.display_name}</strong> ({user.username}, {user.role})
        </p>
      </div>
      <form className="card narrow" onSubmit={changePassword}>
        <h2>Change password</h2>
        {message && <Notice kind={message.kind}>{message.text}</Notice>}
        <Field label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <Field label="New password" type="password" autoComplete="new-password" minLength={8} value={next} onChange={(e) => setNext(e.target.value)} required />
        <Field label="Repeat new password" type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />
        <button className="btn primary">Change password</button>
      </form>
    </>
  );
}
