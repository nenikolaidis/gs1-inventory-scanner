import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, errorMessage, type Role, type User } from "../api";
import { useUser } from "../auth";
import { Field, Modal, Notice, PageHeader, formatDateTime } from "../ui";

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setUsers(await api.get<User[]>("/api/users"));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Users"
        actions={
          <button className="btn primary" onClick={() => setEditing("new")}>
            Add user
          </button>
        }
      />
      <p className="muted">
        Operators can scan, search and print. Admins can also manage products, locations and users,
        and delete any scan.
      </p>
      {error && <Notice kind="error">{error}</Notice>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Name</th>
              <th>Role</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} onClick={() => setEditing(u)} className={u.is_active ? "" : "inactive"}>
                <td data-label="Username"><strong>{u.username}</strong></td>
                <td data-label="Name">{u.display_name}</td>
                <td data-label="Role">{u.role}</td>
                <td data-label="Status">{u.is_active ? "Active" : "Deactivated"}</td>
                <td data-label="Created">{formatDateTime(u.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <UserForm
          user={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}
    </>
  );
}

function UserForm({ user, onClose, onSaved }: { user: User | null; onClose: () => void; onSaved: () => void }) {
  const me = useUser();
  const [username, setUsername] = useState(user?.username ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [role, setRole] = useState<Role>(user?.role ?? "operator");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const isMe = user?.id === me.id;

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      if (user) {
        await api.patch(`/api/users/${user.id}`, {
          display_name: displayName,
          role,
          is_active: isActive,
          ...(password ? { password } : {}),
        });
      } else {
        await api.post("/api/users", { username, display_name: displayName, password, role });
      }
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Modal
      title={user ? `Edit ${user.username}` : "Add user"}
      onClose={onClose}
      footer={
        <button className="btn primary" form="user-form">
          Save
        </button>
      }
    >
      <form id="user-form" onSubmit={submit}>
        {error && <Notice kind="error">{error}</Notice>}
        {!user && (
          <Field label="Username" autoCapitalize="none" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
        )}
        <Field label="Name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        <label className="field">
          <span className="field-label">Role</span>
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} disabled={isMe}>
            <option value="operator">Operator</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        {user && (
          <label className="toggle">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} disabled={isMe} />
            Active (can log in)
          </label>
        )}
        <Field
          label={user ? "New password" : "Password"}
          type="password"
          autoComplete="new-password"
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required={!user}
          hint={user ? "Leave empty to keep the current password. Changing it logs the user out." : "At least 8 characters."}
        />
      </form>
    </Modal>
  );
}
