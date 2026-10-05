import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, errorMessage, type Page } from "../api";
import { Empty, Notice, PageHeader, formatDateTime } from "../ui";

interface AuditEntry {
  id: number;
  created_at: string;
  username: string;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  summary: string;
  details: Record<string, unknown>;
}

const ACTIONS = [
  { value: "", label: "All activity" },
  { value: "stock", label: "Stock corrections" },
  { value: "scan", label: "Deleted scans" },
  { value: "product", label: "Products" },
  { value: "location", label: "Locations" },
  { value: "user", label: "Users" },
  { value: "auth", label: "Logins" },
  { value: "auth.login_failed", label: "Failed logins" },
];

const PAGE_SIZE = 100;

function isChange(v: unknown): v is [unknown, unknown] {
  return Array.isArray(v) && v.length === 2;
}

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

export default function Activity() {
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ q: "", action: "" });
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (offset: number) => {
      setLoading(true);
      setError("");
      try {
        const page = await api.get<Page<AuditEntry>>("/api/audit", { ...filters, limit: PAGE_SIZE, offset });
        setEntries((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setLoading(false);
      }
    },
    [filters],
  );

  useEffect(() => {
    load(0);
  }, [load]);

  function search(e: FormEvent) {
    e.preventDefault();
    setFilters({ ...filters, q });
  }

  return (
    <>
      <PageHeader title="Activity" />
      <p className="muted">
        Changes to products, locations, users and stock corrections, deleted scans, and logins. Scans
        themselves are in History.
      </p>
      <form className="toolbar" onSubmit={search}>
        <input type="search" className="search" placeholder="Search by user or description…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        <select
          value={filters.action}
          onChange={(e) => setFilters({ ...filters, action: e.target.value })}
          aria-label="Type of activity"
          style={{ width: "auto" }}
        >
          {ACTIONS.map((a) => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </select>
      </form>
      {error && <Notice kind="error">{error}</Notice>}
      <p className="muted small">{total} entr{total === 1 ? "y" : "ies"}</p>

      {entries.length === 0 && !loading ? (
        <Empty>No activity found.</Empty>
      ) : (
        <ul className="activity-list">
          {entries.map((e) => {
            const details = Object.entries(e.details);
            const expanded = open === e.id;
            return (
              <li key={e.id} className={e.action === "auth.login_failed" ? "failed" : ""}>
                <button type="button" className="activity-row" onClick={() => setOpen(expanded ? null : e.id)} aria-expanded={expanded} disabled={details.length === 0}>
                  <span className="activity-summary">{e.summary}</span>
                  <span className="muted small">
                    {formatDateTime(e.created_at)} · {e.username || "unknown user"} · <span className="mono">{e.action}</span>
                  </span>
                </button>
                {expanded && (
                  <table className="elements activity-details">
                    <tbody>
                      {details.map(([k, v]) => (
                        <tr key={k}>
                          <td className="muted">{k.replace(/_/g, " ")}</td>
                          <td className="value">{isChange(v) ? `${show(v[0])} → ${show(v[1])}` : show(v)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {entries.length < total && (
        <button className="btn block" onClick={() => load(entries.length)} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </>
  );
}
