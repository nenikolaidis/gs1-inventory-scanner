import { useCallback, useEffect, useState } from "react";

import { api, errorMessage, type CountRow, type StockCount } from "../api";
import { useUser } from "../auth";
import { Link, navigate, usePath } from "../router";
import { Empty, Notice, PageHeader, formatDate, formatDateTime } from "../ui";

const STATUS_LABEL: Record<StockCount["status"], string> = {
  open: "In progress",
  applied: "Applied",
  cancelled: "Cancelled",
};

export default function Counts() {
  const path = usePath();
  const match = path.match(/^\/counts\/(\d+)$/);
  return match ? <CountDetail id={Number(match[1])} /> : <CountList />;
}

function CountList() {
  const [counts, setCounts] = useState<StockCount[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<StockCount[]>("/api/counts").then(setCounts, (e) => setError(errorMessage(e)));
  }, []);

  return (
    <>
      <PageHeader title="Stock counts" />
      <p className="muted">
        To count a location, open <Link to="/scan">Scan</Link>, choose <strong>Count</strong> and scan the
        location's label, then everything on it.
      </p>
      {error && <Notice kind="error">{error}</Notice>}
      {counts.length === 0 ? (
        <Empty>No counts yet.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Location</th>
                <th>Started</th>
                <th>By</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {counts.map((c) => (
                <tr key={c.id} onClick={() => navigate(`/counts/${c.id}`)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && navigate(`/counts/${c.id}`)}>
                  <td data-label="#">{c.id}</td>
                  <td data-label="Location" className="mono"><strong>{c.location.code}</strong></td>
                  <td data-label="Started">{formatDateTime(c.created_at)}</td>
                  <td data-label="By">{c.user?.display_name ?? "—"}</td>
                  <td data-label="Status"><span className={`status ${c.status}`}>{STATUS_LABEL[c.status]}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function gs1Date(iso: string): string {
  return iso.slice(2, 4) + iso.slice(5, 7) + iso.slice(8, 10);
}

function CountDetail({ id }: { id: number }) {
  const user = useUser();
  const [count, setCount] = useState<StockCount | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<StockCount>(`/api/counts/${id}`).then(setCount, (e) => setError(errorMessage(e)));
  }, [id]);

  useEffect(load, [load]);

  async function run(action: () => Promise<StockCount>) {
    setBusy(true);
    setError("");
    try {
      setCount(await action());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function setCounted(row: CountRow, value: string) {
    const quantity = Number(value);
    if (value === "" || Number.isNaN(quantity) || quantity < 0 || quantity === row.counted) return;
    if (row.line_id !== null) {
      run(() => api.patch<StockCount>(`/api/counts/${id}/lines/${row.line_id}`, { quantity }));
    } else {
      // Not scanned yet: add it as if its label had been scanned.
      const barcode =
        (row.sscc ? `(00)${row.sscc}` : "") +
        `(01)${row.gtin}` +
        (row.expiry_date ? `(17)${gs1Date(row.expiry_date)}` : "") +
        (row.lot ? `(10)${row.lot}` : "");
      run(() => api.post<StockCount>(`/api/counts/${id}/scan`, { barcode, quantity }));
    }
  }

  function continueCounting() {
    try {
      sessionStorage.setItem("scan.mode", JSON.stringify("count"));
      sessionStorage.setItem("scan.count", JSON.stringify(count));
    } catch {
      // storage unavailable; the user can scan the location again
    }
    navigate("/scan");
  }

  if (!count) return error ? <Notice kind="error">{error}</Notice> : <p className="muted">Loading…</p>;

  const rows = count.rows ?? [];
  const differences = rows.filter((r) => r.difference !== 0);
  const open = count.status === "open";
  const canCancel = open && (user.role === "admin" || count.user?.id === user.id);

  return (
    <>
      <PageHeader
        title={`Count #${count.id} — ${count.location.code}`}
        actions={
          open && (
            <>
              <button className="btn" onClick={continueCounting}>
                Continue counting
              </button>
              {canCancel && (
                <button
                  className="btn"
                  disabled={busy}
                  onClick={() => window.confirm("Cancel this count? Nothing will change in stock.") && run(() => api.post<StockCount>(`/api/counts/${id}/cancel`))}
                >
                  Cancel count
                </button>
              )}
              {user.role === "admin" && (
                <button
                  className="btn primary"
                  disabled={busy}
                  onClick={() =>
                    window.confirm(
                      differences.length
                        ? `Apply ${differences.length} correction(s) to stock at ${count.location.code}?`
                        : "No differences. Close this count?",
                    ) && run(() => api.post<StockCount>(`/api/counts/${id}/apply`))
                  }
                >
                  Apply to stock
                </button>
              )}
            </>
          )
        }
      />
      <p className="muted">
        <span className={`status ${count.status}`}>{STATUS_LABEL[count.status]}</span> · started {formatDateTime(count.created_at)} by{" "}
        {count.user?.display_name ?? "—"}
        {count.closed_at && ` · ${count.status} ${formatDateTime(count.closed_at)} by ${count.closed_by?.display_name ?? "—"}`}
      </p>
      {error && <Notice kind="error">{error}</Notice>}
      {open && (
        <Notice kind={differences.length ? "warn" : "ok"}>
          {differences.length
            ? `${differences.length} difference(s). Items in stock that weren't counted are treated as missing. Correct a counted quantity below if needed.`
            : "Everything matches."}
          {user.role !== "admin" && " An admin applies the count to stock."}
        </Notice>
      )}

      {rows.length === 0 ? (
        <Empty>Nothing in stock here and nothing counted.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>GTIN</th>
                <th>Lot</th>
                <th>Expiry</th>
                <th>SSCC</th>
                <th className="num">Expected</th>
                <th className="num">Counted</th>
                <th className="num">Difference</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.gtin}|${r.lot}|${r.expiry_date}|${r.sscc}`} className={`static ${r.difference !== 0 ? "diff" : ""}`}>
                  <td data-label="SKU"><strong>{r.product?.sku ?? "—"}</strong></td>
                  <td data-label="GTIN" className="mono">{r.gtin}</td>
                  <td data-label="Lot" className="mono">{r.lot ?? "—"}</td>
                  <td data-label="Expiry">{formatDate(r.expiry_date) || "—"}</td>
                  <td data-label="SSCC" className="mono">{r.sscc ?? "—"}</td>
                  <td data-label="Expected" className="num">{r.expected}</td>
                  <td data-label="Counted" className="num">
                    {open ? (
                      <input
                        className="count-input"
                        type="number"
                        min={0}
                        inputMode="numeric"
                        defaultValue={r.counted}
                        key={r.counted}
                        aria-label={`Counted quantity for ${r.product?.sku ?? r.gtin} ${r.lot ?? ""}`}
                        onBlur={(e) => setCounted(r, e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
                      />
                    ) : (
                      r.counted
                    )}
                  </td>
                  <td data-label="Difference" className={`num ${r.difference < 0 ? "negative" : r.difference > 0 ? "positive" : ""}`}>
                    <strong>
                      {r.difference > 0 ? "+" : ""}
                      {r.difference}
                    </strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
