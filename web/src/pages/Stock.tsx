import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, errorMessage, withParams, type Location, type Movement, type Page, type StockRow } from "../api";
import { useUser } from "../auth";
import { Empty, Field, Modal, Notice, PageHeader, formatDate, formatDateTime } from "../ui";

interface Filters {
  q: string;
  location: string; // "" = all, "none" = no location, else an ID
  expires: string; // "" = any, else days
}

const NO_FILTERS: Filters = { q: "", location: "", expires: "" };

function toParams(f: Filters) {
  return {
    q: f.q,
    location_id: f.location && f.location !== "none" ? f.location : undefined,
    unassigned: f.location === "none" ? true : undefined,
    expires_within_days: f.expires || undefined,
  };
}

interface ExpirySummary {
  warning_days: number;
  expired_lines: number;
  expired_units: number;
  expiring_lines: number;
  expiring_units: number;
}

export function expiryClass(iso: string | null, warningDays = 30): string {
  if (!iso) return "";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = (new Date(iso + "T00:00:00").getTime() - today.getTime()) / 86_400_000;
  return days < 0 ? "expired" : days <= warningDays ? "expiring" : "";
}

export default function Stock() {
  const [draft, setDraft] = useState<Filters>(NO_FILTERS);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [rows, setRows] = useState<StockRow[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [selected, setSelected] = useState<StockRow | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [expiry, setExpiry] = useState<ExpirySummary | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setRows(await api.get<StockRow[]>("/api/stock", toParams(filters)));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
    api.get<ExpirySummary>("/api/stock/expiry").then(setExpiry, () => {});
  }, [load]);

  function showExpiring(days: string) {
    const next = { ...NO_FILTERS, expires: days };
    setDraft(next);
    setFilters(next);
  }

  useEffect(() => {
    api.get<Location[]>("/api/locations", { include_inactive: true }).then(setLocations, () => {});
  }, []);

  function search(e: FormEvent) {
    e.preventDefault();
    setFilters(draft);
  }

  const set = (key: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const next = { ...draft, [key]: e.target.value };
    setDraft(next);
    if (key !== "q") setFilters(next); // dropdowns apply immediately
  };

  const total = rows.reduce((sum, r) => sum + r.quantity, 0);

  return (
    <>
      <PageHeader
        title="Stock"
        actions={
          <a className="btn" href={withParams("/api/stock/export.csv", toParams(filters))} download>
            Export CSV
          </a>
        }
      />
      <form className="filters stock-filters card" onSubmit={search}>
        <input
          type="search"
          placeholder="Search SKU, product, GTIN, lot, SSCC, location…"
          value={draft.q}
          onChange={set("q")}
          aria-label="Search"
        />
        <select value={draft.location} onChange={set("location")} aria-label="Location">
          <option value="">All locations</option>
          <option value="none">No location</option>
          {locations.map((l) => (
            <option key={l.id} value={l.id}>
              {l.code}
            </option>
          ))}
        </select>
        <select value={draft.expires} onChange={set("expires")} aria-label="Expiry">
          <option value="">Any expiry</option>
          <option value="0">Expired or expiring today</option>
          {[...new Set([7, 30, 90, expiry?.warning_days ?? 30])]
            .sort((a, b) => a - b)
            .map((d) => (
              <option key={d} value={d}>
                Expires within {d} days
              </option>
            ))}
        </select>
        <button className="btn primary">Search</button>
      </form>

      {expiry && (expiry.expired_lines > 0 || expiry.expiring_lines > 0) && (
        <div className="notice warn expiry-banner" role="status">
          <span>
            {expiry.expired_lines > 0 && (
              <strong>
                {expiry.expired_units} unit(s) expired ({expiry.expired_lines} line(s)).{" "}
              </strong>
            )}
            {expiry.expiring_lines > 0 &&
              `${expiry.expiring_units} unit(s) expire within ${expiry.warning_days} days (${expiry.expiring_lines} line(s)).`}
          </span>
          <button type="button" className="btn small" onClick={() => showExpiring(String(expiry.warning_days))}>
            Show them
          </button>
        </div>
      )}
      {error && <Notice kind="error">{error}</Notice>}
      <p className="muted small">
        {rows.length} line(s), {total} unit(s)
      </p>

      {rows.length === 0 && !loading ? (
        <Empty>No stock found. Receive pallets on the Scan screen to add stock.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Location</th>
                <th>SKU</th>
                <th>Product</th>
                <th>GTIN</th>
                <th>Lot</th>
                <th>Expiry</th>
                <th>SSCC</th>
                <th className="num">Qty</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} onClick={() => setSelected(r)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSelected(r)}>
                  <td data-label="Location" className="mono">{r.location?.code ?? "—"}</td>
                  <td data-label="SKU"><strong>{r.product?.sku ?? "—"}</strong></td>
                  <td data-label="Product">{r.product?.name || "—"}</td>
                  <td data-label="GTIN" className="mono">{r.gtin}</td>
                  <td data-label="Lot" className="mono">{r.lot ?? "—"}</td>
                  <td data-label="Expiry" className={expiryClass(r.expiry_date, expiry?.warning_days)}>{formatDate(r.expiry_date) || "—"}</td>
                  <td data-label="SSCC" className="mono">{r.sscc ?? "—"}</td>
                  <td data-label="Qty" className={`num ${r.quantity < 0 ? "negative" : ""}`}><strong>{r.quantity}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <StockDetails
          row={selected}
          onClose={() => setSelected(null)}
          onChanged={() => {
            setSelected(null);
            load();
          }}
        />
      )}
    </>
  );
}

const KIND_LABEL: Record<Movement["kind"], string> = {
  receive: "Received",
  pick: "Picked",
  move: "Moved",
  adjust: "Adjusted",
};

function StockDetails({ row, onClose, onChanged }: { row: StockRow; onClose: () => void; onChanged: () => void }) {
  const user = useUser();
  const [movements, setMovements] = useState<Movement[]>([]);
  const [quantity, setQuantity] = useState(String(row.quantity));
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<Page<Movement>>("/api/movements", {
        gtin: row.gtin,
        lot: row.lot ?? undefined,
        sscc: row.sscc ?? undefined,
        location_id: row.location?.id,
        unassigned: row.location ? undefined : true,
        limit: 50,
      })
      .then(
        // The API filters by GTIN, lot and SSCC; also match the expiry date exactly.
        (page) => setMovements(page.items.filter((m) => m.expiry_date === row.expiry_date && m.lot === row.lot && m.sscc === row.sscc)),
        (e) => setError(errorMessage(e)),
      );
  }, [row]);

  async function adjust(e: FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/stock/adjust", {
        location_id: row.location?.id ?? null,
        gtin: row.gtin,
        lot: row.lot,
        expiry_date: row.expiry_date,
        sscc: row.sscc,
        quantity: Number(quantity),
        note,
      });
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const details: [string, string | null | undefined][] = [
    ["Location", row.location?.code ?? "No location"],
    ["SKU", row.product?.sku],
    ["Product", row.product?.name],
    ["GTIN", row.gtin],
    ["Lot", row.lot],
    ["Expiry", formatDate(row.expiry_date)],
    ["SSCC", row.sscc],
    ["Quantity", String(row.quantity)],
  ];

  return (
    <Modal title={row.product?.sku ?? `GTIN ${row.gtin}`} onClose={onClose}>
      {error && <Notice kind="error">{error}</Notice>}
      <dl className="details">
        {details
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
      </dl>

      {user.role === "admin" && (
        <form className="adjust-form" onSubmit={adjust}>
          <h3 className="section-title">Correct the quantity</h3>
          <div className="form-grid">
            <Field label="Actual quantity" type="number" min={0} inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} required />
            <Field label="Reason" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. damaged, recount" required />
          </div>
          <button className="btn primary" disabled={quantity === String(row.quantity)}>
            Save correction
          </button>
        </form>
      )}

      <h3 className="section-title">History</h3>
      {movements.length === 0 ? (
        <p className="muted">No movements.</p>
      ) : (
        <ul className="movement-list">
          {movements.map((m) => (
            <li key={m.id}>
              <span className={`qty ${m.quantity < 0 ? "out" : "in"}`}>
                {m.quantity > 0 ? "+" : ""}
                {m.quantity}
              </span>
              <span>
                {KIND_LABEL[m.kind]}
                {m.note && <span className="muted"> — {m.note}</span>}
                <span className="muted small">
                  <br />
                  {formatDateTime(m.created_at)} · {m.user?.display_name ?? "import"}
                  {m.scan_id && ` · scan #${m.scan_id}`}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
