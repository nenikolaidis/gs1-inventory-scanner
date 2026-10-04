import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, errorMessage, withParams, type Location, type Page, type Scan } from "../api";
import { useUser } from "../auth";
import { Empty, Modal, Notice, PageHeader, formatDate, formatDateTime } from "../ui";

const PAGE_SIZE = 50;

interface Filters {
  q: string;
  location_id: string;
  date_from: string;
  date_to: string;
}

const NO_FILTERS: Filters = { q: "", location_id: "", date_from: "", date_to: "" };

export default function History() {
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [scans, setScans] = useState<Scan[]>([]);
  const [total, setTotal] = useState(0);
  const [locations, setLocations] = useState<Location[]>([]);
  const [selected, setSelected] = useState<Scan | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (offset: number) => {
      setLoading(true);
      setError("");
      try {
        const page = await api.get<Page<Scan>>("/api/scans", { ...filters, limit: PAGE_SIZE, offset });
        setScans((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
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

  useEffect(() => {
    api.get<Location[]>("/api/locations", { include_inactive: true }).then(setLocations, () => {});
  }, []);

  function search(e: FormEvent) {
    e.preventDefault();
    setFilters(draft);
  }

  const set = (key: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft({ ...draft, [key]: e.target.value });

  return (
    <>
      <PageHeader
        title="Scan history"
        actions={
          <a className="btn" href={withParams("/api/scans/export.csv", { ...filters })} download>
            Export CSV
          </a>
        }
      />
      <form className="filters card" onSubmit={search}>
        <input
          type="search"
          placeholder="Search SKU, GTIN, SSCC, lot, serial, location…"
          value={draft.q}
          onChange={set("q")}
          aria-label="Search"
        />
        <select value={draft.location_id} onChange={set("location_id")} aria-label="Location">
          <option value="">All locations</option>
          {locations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.code}
            </option>
          ))}
        </select>
        <label className="inline-field">
          From <input type="date" value={draft.date_from} onChange={set("date_from")} />
        </label>
        <label className="inline-field">
          To <input type="date" value={draft.date_to} onChange={set("date_to")} />
        </label>
        <button className="btn primary">Search</button>
      </form>

      {error && <Notice kind="error">{error}</Notice>}
      <p className="muted small">{total} scan(s)</p>

      {scans.length === 0 && !loading ? (
        <Empty>No scans found.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Location</th>
                <th>SKU</th>
                <th>GTIN / SSCC</th>
                <th>Lot</th>
                <th className="num">Qty</th>
                <th>Expiry</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {scans.map((s) => (
                <tr key={s.id} onClick={() => setSelected(s)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSelected(s)}>
                  <td data-label="When">
                    {formatDateTime(s.created_at)}
                    {s.warnings.length > 0 && <span title="Has warnings"> ⚠</span>}
                  </td>
                  <td data-label="Location">{s.location?.code ?? "—"}</td>
                  <td data-label="SKU">{s.sku ?? "—"}</td>
                  <td data-label="GTIN / SSCC" className="mono">{s.gtin ?? s.sscc ?? "—"}</td>
                  <td data-label="Lot" className="mono">{s.lot ?? "—"}</td>
                  <td data-label="Qty" className="num">{s.quantity ?? "—"}</td>
                  <td data-label="Expiry">{formatDate(s.expiry_date) || "—"}</td>
                  <td data-label="By">{s.user?.display_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {scans.length < total && (
        <button className="btn block" onClick={() => load(scans.length)} disabled={loading}>
          {loading ? "Loading…" : "Load more"}
        </button>
      )}

      {selected && (
        <ScanDetails
          scan={selected}
          onClose={() => setSelected(null)}
          onDeleted={() => {
            setSelected(null);
            load(0);
          }}
        />
      )}
    </>
  );
}

function ScanDetails({ scan, onClose, onDeleted }: { scan: Scan; onClose: () => void; onDeleted: () => void }) {
  const user = useUser();
  const [error, setError] = useState("");

  async function remove() {
    if (!window.confirm(`Delete scan #${scan.id}? This can't be undone.`)) return;
    try {
      await api.delete(`/api/scans/${scan.id}`);
      onDeleted();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const rows: [string, string | number | null | undefined][] = [
    ["Scanned", formatDateTime(scan.created_at)],
    ["By", scan.user?.display_name],
    ["Location", scan.location?.code],
    ["SKU", scan.sku],
    ["Product", scan.product?.name],
    ["Quantity", scan.quantity],
    ["Production date", formatDate(scan.production_date)],
    ["Best before", formatDate(scan.best_before)],
    ["Expiry", formatDate(scan.expiry_date)],
    ["Note", scan.note],
    ["Scanned text", scan.raw_barcode],
  ];

  return (
    <Modal
      title={`Scan #${scan.id}`}
      onClose={onClose}
      footer={
        <>
          {(user.role === "admin" || scan.user?.id === user.id) && (
            <button className="btn danger" onClick={remove}>
              Delete
            </button>
          )}
          <a className="btn" href={`/api/scans/${scan.id}/label.pdf`} target="_blank" rel="noreferrer">
            Print label
          </a>
        </>
      }
    >
      {error && <Notice kind="error">{error}</Notice>}
      {scan.warnings.length > 0 && (
        <ul className="warnings">
          {scan.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}
      <dl className="details">
        {rows
          .filter(([, v]) => v !== null && v !== undefined && v !== "")
          .map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
      </dl>
      <h3 className="section-title">GS1 data</h3>
      <table className="elements">
        <tbody>
          {scan.elements.map((el, i) => (
            <tr key={i}>
              <td className="ai">({el.ai})</td>
              <td className="muted">{el.title}</td>
              <td className="value">{el.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}
