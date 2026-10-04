// The scan screen: built for hardware scanners (keyboard wedge, Enter suffix)
// on handhelds, tablets and desktops. One input takes both shelf location
// labels and GS1 pallet/carton barcodes.

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { api, errorMessage, type Location, type Resolved, type Scan } from "../api";
import { useUser } from "../auth";
import { feedback } from "../feedback";
import { Field, formatDate, locationLabel } from "../ui";

interface Pending {
  barcode: string;
  resolved: Resolved;
  sku: string;
  quantity: string;
  note: string;
}

interface Flash {
  kind: "ok" | "warn" | "error";
  text: string;
}

const UNDO_MINUTES = 10;

function loadStored<T>(storage: Storage, key: string, fallback: T): T {
  try {
    const raw = storage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

function store(storage: Storage, key: string, value: unknown) {
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    // storage unavailable (private mode); settings just won't persist
  }
}

export default function ScanPage() {
  const user = useUser();
  const inputRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [location, setLocation] = useState<Location | null>(() =>
    loadStored(sessionStorage, "scan.location", null),
  );
  const [quickSave, setQuickSave] = useState(() => loadStored(localStorage, "scan.quickSave", true));
  const [softKeyboard, setSoftKeyboard] = useState(() =>
    loadStored(localStorage, "scan.softKeyboard", true),
  );
  const [pending, setPending] = useState<Pending | null>(null);
  const [recent, setRecent] = useState<Scan[]>([]);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => store(sessionStorage, "scan.location", location), [location]);
  useEffect(() => store(localStorage, "scan.quickSave", quickSave), [quickSave]);
  useEffect(() => store(localStorage, "scan.softKeyboard", softKeyboard), [softKeyboard]);

  const focusInput = useCallback(() => {
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  useEffect(focusInput, [focusInput]);

  function show(kind: Flash["kind"], message: string) {
    setFlash({ kind, text: message });
    feedback(kind);
  }

  async function save(p: Pending) {
    setBusy(true);
    try {
      const scan = await api.post<Scan>("/api/scans", {
        barcode: p.barcode,
        location_id: location?.id ?? null,
        sku: p.sku.trim() || null,
        quantity: p.quantity.trim() === "" ? null : Number(p.quantity),
        note: p.note,
      });
      setRecent((r) => [scan, ...r].slice(0, 20));
      setPending(null);
      show(scan.warnings.length ? "warn" : "ok", `Saved ${describe(scan)}`);
    } catch (e) {
      show("error", errorMessage(e));
    } finally {
      setBusy(false);
      focusInput();
    }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const barcode = text.trim();
    setText("");
    if (!barcode || busy) return;
    setBusy(true);
    try {
      const resolved = await api.post<Resolved>("/api/resolve", { text: barcode });
      if (resolved.kind === "location" && resolved.location) {
        setLocation(resolved.location);
        show("ok", `Location set to ${resolved.location.code}`);
      } else if (resolved.kind === "unknown") {
        show("error", resolved.parse?.warnings[0] ?? "Not a GS1 barcode or known location.");
      } else if (pending) {
        show("error", "Save or discard the scan below before scanning the next one.");
      } else {
        const qty = resolved.parse?.elements.find((el) => el.ai === "37")?.value ?? "";
        const p: Pending = {
          barcode,
          resolved,
          sku: resolved.product?.sku ?? "",
          quantity: qty ? String(Number(qty)) : "",
          note: "",
        };
        const clean = !resolved.parse?.warnings.length;
        if (quickSave && clean) {
          setBusy(false);
          await save(p);
          return;
        }
        setPending(p);
        show(clean ? "ok" : "warn", clean ? "Check the details and save." : "Check the warnings before saving.");
      }
    } catch (err) {
      show("error", errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function undo(scan: Scan) {
    try {
      await api.delete(`/api/scans/${scan.id}`);
      setRecent((r) => r.filter((s) => s.id !== scan.id));
      show("ok", `Removed scan #${scan.id}`);
    } catch (e) {
      show("error", errorMessage(e));
    }
    focusInput();
  }

  function canUndo(scan: Scan): boolean {
    if (user.role === "admin") return true;
    const age = Date.now() - new Date(scan.created_at).getTime();
    return scan.user?.id === user.id && age < UNDO_MINUTES * 60_000;
  }

  return (
    <div className="scan-page">
      <form onSubmit={submit} className="scan-form">
        <label htmlFor="scan-input" className="visually-hidden">
          Scan a barcode
        </label>
        <input
          id="scan-input"
          ref={inputRef}
          className="scan-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={location ? "Scan pallet or carton…" : "Scan a location or pallet…"}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          inputMode={softKeyboard ? "text" : "none"}
          enterKeyHint="go"
          disabled={busy && !text}
        />
        <button className="btn primary" disabled={busy || !text.trim()}>
          Go
        </button>
      </form>

      <div className="scan-toolbar">
        <div className={`location-chip ${location ? "set" : ""}`}>
          <span className="muted">Location</span>
          <strong>{location ? locationLabel(location) : "none"}</strong>
          {location && (
            <button
              type="button"
              className="btn ghost small"
              onClick={() => {
                setLocation(null);
                focusInput();
              }}
            >
              Clear
            </button>
          )}
        </div>
        <label className="toggle">
          <input type="checkbox" checked={quickSave} onChange={(e) => setQuickSave(e.target.checked)} />
          Quick save
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={softKeyboard}
            onChange={(e) => {
              setSoftKeyboard(e.target.checked);
              focusInput();
            }}
          />
          On-screen keyboard
        </label>
      </div>

      {flash && (
        <div className={`flash ${flash.kind}`} role={flash.kind === "error" ? "alert" : "status"}>
          {flash.text}
        </div>
      )}

      {pending && (
        <PendingCard
          pending={pending}
          busy={busy}
          onChange={setPending}
          onSave={() => save(pending)}
          onDiscard={() => {
            setPending(null);
            setFlash(null);
            focusInput();
          }}
        />
      )}

      <section>
        <h2 className="section-title">Scanned this session</h2>
        {recent.length === 0 ? (
          <p className="empty">
            {location
              ? "Scan a pallet or carton label."
              : "Scan a shelf location label first, or scan a pallet to record it without a location."}
          </p>
        ) : (
          <ul className="recent-list">
            {recent.map((scan) => (
              <li key={scan.id} className="recent-item">
                <div>
                  <strong>{describe(scan)}</strong>
                  <div className="muted small">
                    #{scan.id} · {scan.location?.code ?? "no location"}
                    {scan.expiry_date && ` · expires ${formatDate(scan.expiry_date)}`}
                    {scan.warnings.length > 0 && " · ⚠ has warnings"}
                  </div>
                </div>
                {canUndo(scan) && (
                  <button type="button" className="btn ghost small" onClick={() => undo(scan)}>
                    Undo
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function describe(scan: Scan): string {
  const what = scan.sku ?? (scan.gtin ? `GTIN ${scan.gtin}` : scan.sscc ? `SSCC ${scan.sscc}` : scan.gs1_hri);
  const parts = [what];
  if (scan.lot) parts.push(`lot ${scan.lot}`);
  if (scan.quantity !== null) parts.push(`× ${scan.quantity}`);
  return parts.join(" · ");
}

function PendingCard({
  pending,
  busy,
  onChange,
  onSave,
  onDiscard,
}: {
  pending: Pending;
  busy: boolean;
  onChange: (p: Pending) => void;
  onSave: () => void;
  onDiscard: () => void;
}) {
  const parse = pending.resolved.parse;
  const product = pending.resolved.product;
  return (
    <form
      className="card pending-card"
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <h2>Ready to save</h2>
      {parse && parse.warnings.length > 0 && (
        <ul className="warnings">
          {parse.warnings.map((w) => (
            <li key={w}>⚠ {w}</li>
          ))}
        </ul>
      )}
      <table className="elements">
        <tbody>
          {parse?.elements.map((el, i) => (
            <tr key={i}>
              <td className="ai">({el.ai})</td>
              <td className="muted">{el.title}</td>
              <td className="value">{el.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="form-grid">
        <Field
          label="SKU"
          value={pending.sku}
          onChange={(e) => onChange({ ...pending, sku: e.target.value })}
          readOnly={!!product}
          placeholder={product ? "" : "Optional; remembered for this GTIN"}
          hint={product?.name || undefined}
        />
        <label className="field">
          <span className="field-label">Quantity</span>
          <input
            type="number"
            min={0}
            inputMode="numeric"
            value={pending.quantity}
            onChange={(e) => onChange({ ...pending, quantity: e.target.value })}
          />
        </label>
        <label className="field span-2">
          <span className="field-label">Note</span>
          <input value={pending.note} onChange={(e) => onChange({ ...pending, note: e.target.value })} />
        </label>
      </div>
      <div className="row-actions">
        <button type="button" className="btn" onClick={onDiscard}>
          Discard
        </button>
        <button className="btn primary" disabled={busy}>
          Save
        </button>
      </div>
    </form>
  );
}
