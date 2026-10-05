// The scan screen: built for hardware scanners (keyboard wedge, Enter suffix)
// on handhelds, tablets and desktops. One input takes both shelf location
// labels and GS1 pallet/carton barcodes, in one of four modes.

import { Suspense, lazy, useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import {
  api,
  errorMessage,
  type Action,
  type Location,
  type Resolved,
  type Scan,
  type StockCount,
  type StockRow,
} from "../api";
import { useUser } from "../auth";
import { Link } from "../router";
import { useConfig } from "../config";
import { feedback } from "../feedback";
import {
  cachedLocation,
  enqueue,
  isOffline,
  newRef,
  refreshLocationCache,
  syncQueue,
  updateQueued,
  useQueue,
  type QueuedScan,
  type ScanBody,
} from "../offline";
import { Field, formatDate, locationLabel } from "../ui";

type Mode = "receive" | "pick" | "move" | "count" | "find";

const CameraScanner = lazy(() => import("../camera"));

function cameraAvailable(): boolean {
  return window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia);
}

const MODES: { mode: Mode; label: string; hint: string }[] = [
  { mode: "receive", label: "Receive", hint: "Scan the location, then the pallets that arrive there." },
  { mode: "pick", label: "Pick", hint: "Scan what leaves stock. Scan its location first if it's in several places." },
  { mode: "move", label: "Move", hint: "Scan the pallet or item, then the location it goes to." },
  { mode: "count", label: "Count", hint: "Scan the location, then everything on it. Review the differences when done." },
  { mode: "find", label: "Find", hint: "Scan an item to see where it is, or a location to see what's there." },
];

interface Pending {
  ref: string; // client_ref: the same for every upload attempt of this scan
  offline: boolean; // made without a connection; the server checks it on upload
  barcode: string;
  resolved: Resolved;
  action: Action;
  sku: string;
  quantity: string;
  note: string;
}

interface Flash {
  kind: "ok" | "warn" | "error";
  text: string;
}

interface Found {
  title: string;
  rows: StockRow[];
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

function aiValue(resolved: Resolved, ai: string): string | undefined {
  return resolved.parse?.elements.find((el) => el.ai === ai)?.value;
}

export default function ScanPage() {
  const user = useUser();
  const config = useConfig();
  const inputRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<Mode>(() => loadStored(sessionStorage, "scan.mode", "receive"));
  const [location, setLocation] = useState<Location | null>(() =>
    loadStored(sessionStorage, "scan.location", null),
  );
  const [quickSave, setQuickSave] = useState(() => loadStored(localStorage, "scan.quickSave", true));
  const [softKeyboard, setSoftKeyboard] = useState(() =>
    loadStored(localStorage, "scan.softKeyboard", true),
  );
  const [pending, setPending] = useState<Pending | null>(null);
  const [found, setFound] = useState<Found | null>(null);
  const [count, setCount] = useState<StockCount | null>(() => loadStored(sessionStorage, "scan.count", null));
  const [countPending, setCountPending] = useState<{ barcode: string; label: string; quantity: string } | null>(null);
  const [recent, setRecent] = useState<Scan[]>([]);
  const [flash, setFlash] = useState<Flash | null>(null);
  const [busy, setBusy] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const queue = useQueue();

  useEffect(() => store(sessionStorage, "scan.mode", mode), [mode]);
  useEffect(() => store(sessionStorage, "scan.count", count), [count]);
  useEffect(() => store(sessionStorage, "scan.location", location), [location]);
  useEffect(() => store(localStorage, "scan.quickSave", quickSave), [quickSave]);
  useEffect(() => store(localStorage, "scan.softKeyboard", softKeyboard), [softKeyboard]);

  const focusInput = useCallback(() => {
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  useEffect(focusInput, [focusInput]);

  // Upload scans queued while offline: now, when the connection returns, and every 20 s.
  useEffect(() => {
    const sync = () =>
      syncQueue((scan) => setRecent((r) => [scan, ...r].slice(0, 20))).then((n) => {
        if (n) show("ok", `Uploaded ${n} scan(s) made offline`);
      });
    refreshLocationCache();
    sync();
    window.addEventListener("online", sync);
    const timer = window.setInterval(() => navigator.onLine && sync(), 20_000);
    return () => {
      window.removeEventListener("online", sync);
      window.clearInterval(timer);
    };
  }, []);

  function show(kind: Flash["kind"], message: string) {
    setFlash({ kind, text: message });
    feedback(kind);
  }

  function changeMode(next: Mode) {
    setMode(next);
    // "Into" (receive) and "From" (pick, move) mean different things; start fresh.
    setLocation(null);
    setPending(null);
    setFound(null);
    setCountPending(null);
    setFlash(null);
    focusInput();
  }

  async function addToCount(barcode: string, quantity: number | null) {
    if (!count) return;
    try {
      const updated = await api.post<StockCount>(`/api/counts/${count.id}/scan`, { barcode, quantity });
      setCount(updated);
      setCountPending(null);
      show("ok", "Counted");
    } catch (e) {
      show("error", errorMessage(e));
    }
    focusInput();
  }

  async function countScan(barcode: string, resolved: Resolved) {
    if (resolved.kind === "location" && resolved.location) {
      const started = await api.post<StockCount>("/api/counts", { location_id: resolved.location.id });
      setCount(started);
      setCountPending(null);
      const counted = started.rows?.filter((r) => r.counted > 0).length ?? 0;
      show("ok", `Counting ${started.location.code} (count #${started.id})${counted ? `, ${counted} item(s) already counted` : ""}`);
      return;
    }
    if (!count || count.status !== "open") {
      show("error", "Scan the location you are counting first.");
      return;
    }
    if (countPending) {
      show("error", "Enter the quantity below first, or discard it.");
      return;
    }
    const qty = aiValue(resolved, "37");
    const hasGtin = Boolean(aiValue(resolved, "01") ?? aiValue(resolved, "02"));
    if (qty || !hasGtin) {
      // Quantity on the label, or an SSCC-only pallet label (counted as the whole pallet).
      await addToCount(barcode, null);
      return;
    }
    setCountPending({ barcode, label: resolved.product?.sku ?? resolved.parse?.hri ?? barcode, quantity: "" });
    show("ok", "Enter the counted quantity.");
  }

  async function save(p: Pending, toLocation: Location | null = null) {
    setBusy(true);
    const body: ScanBody = {
      barcode: p.barcode,
      action: p.action,
      location_id: location?.id ?? null,
      to_location_id: toLocation?.id ?? null,
      sku: p.sku.trim() || null,
      quantity: p.quantity.trim() === "" ? null : Number(p.quantity),
      note: p.note,
      client_ref: p.ref,
    };
    try {
      const scan = await api.post<Scan>("/api/scans", body);
      setRecent((r) => [scan, ...r].slice(0, 20));
      setPending(null);
      const lastWarning = scan.warnings[scan.warnings.length - 1];
      show(lastWarning ? "warn" : "ok", lastWarning ? `${describe(scan)}. ⚠ ${lastWarning}` : describe(scan));
    } catch (e) {
      if (isOffline(e)) {
        const where = toLocation ? ` → ${toLocation.code}` : location ? ` at ${location.code}` : "";
        enqueue(body, `${p.action} ${p.resolved.parse?.hri || p.barcode}${where}`);
        setPending(null);
        show("warn", "No connection: saved on this device. It uploads automatically.");
      } else {
        show("error", errorMessage(e));
      }
    } finally {
      setBusy(false);
      focusInput();
    }
  }

  function offlineResolve(barcode: string): Resolved {
    const cached = cachedLocation(barcode);
    if (cached) return { kind: "location", location: cached, parse: null, product: null };
    return {
      kind: "gs1",
      location: null,
      product: null,
      parse: { elements: [], warnings: ["No connection: the barcode is checked when it's uploaded."], hri: barcode },
    };
  }

  async function find(resolved: Resolved) {
    let params: Record<string, string | number>;
    let title: string;
    if (resolved.kind === "location" && resolved.location) {
      params = { location_id: resolved.location.id };
      title = `Stock at ${resolved.location.code}`;
    } else {
      const sscc = aiValue(resolved, "00");
      const gtin = aiValue(resolved, "01") ?? aiValue(resolved, "02");
      if (sscc) params = { sscc };
      else if (gtin) params = { gtin };
      else {
        show("error", "This label has no GTIN or SSCC to look up.");
        return;
      }
      title = resolved.product
        ? `${resolved.product.sku}${resolved.product.name ? ` — ${resolved.product.name}` : ""}`
        : sscc
          ? `Pallet ${sscc}`
          : `GTIN ${gtin}`;
    }
    const rows = await api.get<StockRow[]>("/api/stock", params);
    setFound({ title, rows });
    show(rows.length ? "ok" : "warn", rows.length ? `${rows.length} stock line(s) found` : "Not in stock");
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const barcode = text.trim();
    setText("");
    handle(barcode);
  }

  async function handle(barcode: string) {
    if (!barcode || busy) return;
    setBusy(true);
    try {
      let resolved: Resolved;
      let offline = false;
      try {
        resolved = await api.post<Resolved>("/api/resolve", { text: barcode });
      } catch (err) {
        if (!isOffline(err)) throw err;
        if (mode === "find" || mode === "count") {
          show("error", "No connection. Find and Count need the server.");
          return;
        }
        resolved = offlineResolve(barcode);
        offline = true;
      }

      if (resolved.kind === "unknown") {
        show("error", resolved.parse?.warnings[0] ?? "Not a GS1 barcode or known location.");
        return;
      }
      if (mode === "find") {
        await find(resolved);
        return;
      }
      if (mode === "count") {
        await countScan(barcode, resolved);
        return;
      }
      if (resolved.kind === "location" && resolved.location) {
        // While a move waits for its destination, a location scan completes it.
        if (pending?.action === "move") {
          setBusy(false);
          await save(pending, resolved.location);
          return;
        }
        setLocation(resolved.location);
        show("ok", `${mode === "receive" ? "Receiving into" : "Working from"} ${resolved.location.code}`);
        return;
      }
      if (pending) {
        show("error", "Finish or discard the scan below before scanning the next one.");
        return;
      }

      const qty = aiValue(resolved, "37");
      const hasGtin = Boolean(aiValue(resolved, "01") ?? aiValue(resolved, "02"));
      const hasSscc = Boolean(aiValue(resolved, "00"));
      const p: Pending = {
        ref: newRef(),
        offline,
        barcode,
        resolved,
        action: mode === "receive" && !hasGtin && !offline ? "log" : mode,
        sku: resolved.product?.sku ?? "",
        quantity: qty ? String(Number(qty)) : "",
        note: "",
      };
      const clean = !resolved.parse?.warnings.length;

      if (mode === "move") {
        setPending(p);
        show(clean ? "ok" : "warn", "Now scan the destination location.");
        return;
      }
      // Quick save only when nothing needs checking: no warnings, and a known
      // quantity (or, for a pick, a whole pallet identified by its SSCC).
      const quantityKnown = p.quantity !== "" || (mode === "pick" && hasSscc);
      if (quickSave && clean && quantityKnown && p.action !== "log") {
        setBusy(false);
        await save(p);
        return;
      }
      setPending(p);
      if (p.action === "log") show("warn", "This label has no GTIN, so it can't be added to stock.");
      else if (offline) show("warn", "No connection. Enter the quantity if it isn't on the label, then save.");
      else if (!clean) show("warn", "Check the warnings before saving.");
      else show("ok", "Enter the quantity and save.");
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
      show("ok", `Undone: ${describe(scan)}`);
    } catch (e) {
      show("error", errorMessage(e));
    }
    focusInput();
  }

  async function printLabel(scan: Scan) {
    try {
      await api.post(`/api/scans/${scan.id}/print`);
      show("ok", `Label for scan #${scan.id} sent to the printer`);
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

  const modeInfo = MODES.find((m) => m.mode === mode)!;
  const locationTitle = mode === "receive" ? "Into" : "From";

  return (
    <div className="scan-page">
      <div className="segmented" role="tablist" aria-label="Scan mode">
        {MODES.map((m) => (
          <button
            key={m.mode}
            type="button"
            role="tab"
            aria-selected={mode === m.mode}
            className={mode === m.mode ? "active" : ""}
            onClick={() => changeMode(m.mode)}
          >
            {m.label}
          </button>
        ))}
      </div>
      <p className="muted small mode-hint">{modeInfo.hint}</p>

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
          placeholder={pending?.action === "move" ? "Scan destination location…" : "Scan…"}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck={false}
          inputMode={softKeyboard ? "text" : "none"}
          enterKeyHint="go"
          disabled={busy && !text}
        />
        {cameraAvailable() && (
          <button type="button" className="btn camera-button" onClick={() => setCameraOpen(true)} aria-label="Scan with camera" title="Scan with camera">
            📷
          </button>
        )}
        <button className="btn primary" disabled={busy || !text.trim()}>
          Go
        </button>
      </form>

      {cameraOpen && (
        <Suspense fallback={<div className="camera-overlay"><div className="camera-bar">Starting camera…</div></div>}>
          <CameraScanner
            onResult={(scanned) => {
              setCameraOpen(false);
              handle(scanned);
            }}
            onClose={() => {
              setCameraOpen(false);
              focusInput();
            }}
          />
        </Suspense>
      )}

      {queue.length > 0 && <QueuePanel items={queue} onSync={() => syncQueue((scan) => setRecent((r) => [scan, ...r].slice(0, 20)))} />}

      <div className="scan-toolbar">
        {mode !== "find" && mode !== "count" && (
          <div className={`location-chip ${location ? "set" : ""}`}>
            <span className="muted">{locationTitle}</span>
            <strong>{location ? locationLabel(location) : mode === "receive" ? "no location" : "any location"}</strong>
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
        )}
        {(mode === "receive" || mode === "pick") && (
          <label className="toggle">
            <input type="checkbox" checked={quickSave} onChange={(e) => setQuickSave(e.target.checked)} />
            Quick save
          </label>
        )}
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
          // For a move, Enter returns to the scan input to scan the destination.
          onSave={() => (pending.action === "move" ? focusInput() : save(pending))}
          onDiscard={() => {
            setPending(null);
            setFlash(null);
            focusInput();
          }}
        />
      )}

      {mode === "find" && found && <FoundList found={found} />}

      {mode === "count" && (
        <CountPanel
          count={count}
          pending={countPending}
          onPendingChange={setCountPending}
          onAdd={() => countPending && addToCount(countPending.barcode, Number(countPending.quantity))}
          onDiscard={() => {
            setCountPending(null);
            focusInput();
          }}
        />
      )}

      {mode !== "find" && mode !== "count" && (
        <section>
          <h2 className="section-title">This session</h2>
          {recent.length === 0 ? (
            <p className="empty">Nothing scanned yet.</p>
          ) : (
            <ul className="recent-list">
              {recent.map((scan) => (
                <li key={scan.id} className="recent-item">
                  <div>
                    <strong>{describe(scan)}</strong>
                    <div className="muted small">
                      #{scan.id}
                      {scan.lot && ` · lot ${scan.lot}`}
                      {scan.expiry_date && ` · expires ${formatDate(scan.expiry_date)}`}
                      {scan.warnings.length > 0 && " · ⚠ has warnings"}
                    </div>
                  </div>
                  <div className="row-buttons">
                    {config?.label_printer && scan.action !== "log" && (
                      <button type="button" className="btn ghost small" onClick={() => printLabel(scan)}>
                        Label
                      </button>
                    )}
                    {canUndo(scan) && (
                      <button type="button" className="btn ghost small" onClick={() => undo(scan)}>
                        Undo
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

function itemName(scan: Scan): string {
  return scan.sku ?? (scan.gtin ? `GTIN ${scan.gtin}` : scan.sscc ? `SSCC ${scan.sscc}` : scan.gs1_hri);
}

export function describe(scan: Scan): string {
  const what = itemName(scan);
  const qty = scan.quantity !== null ? `${scan.quantity} × ` : "";
  const movedIn = scan.movements.find((m) => m.quantity > 0);
  const movedOut = scan.movements.find((m) => m.quantity < 0);
  switch (scan.action) {
    case "receive":
      return `Received ${qty}${what} into ${movedIn?.location?.code ?? "no location"}`;
    case "pick":
      return `Picked ${qty}${what} from ${movedOut?.location?.code ?? "no location"}`;
    case "move":
      return `Moved ${qty}${what}: ${movedOut?.location?.code ?? "no location"} → ${movedIn?.location?.code ?? "?"}`;
    default:
      return `Logged ${what}`;
  }
}

function QueuePanel({ items, onSync }: { items: QueuedScan[]; onSync: () => void }) {
  const waiting = items.filter((i) => !i.error).length;
  const failed = items.filter((i) => i.error);
  return (
    <section className="card queue-panel">
      <div className="page-header">
        <h2>
          {waiting > 0 ? `${waiting} scan(s) waiting to upload` : "Scans that need attention"}
        </h2>
        {waiting > 0 && (
          <button type="button" className="btn small" onClick={onSync}>
            Upload now
          </button>
        )}
      </div>
      {failed.map((item) => (
        <QueueProblem key={item.body.client_ref} item={item} />
      ))}
    </section>
  );
}

function QueueProblem({ item }: { item: QueuedScan }) {
  const [quantity, setQuantity] = useState(item.body.quantity === null ? "" : String(item.body.quantity));
  return (
    <form
      className="queue-problem"
      onSubmit={(e) => {
        e.preventDefault();
        updateQueued(item.body.client_ref, (it) => ({
          ...it,
          error: undefined,
          body: { ...it.body, quantity: quantity === "" ? null : Number(quantity) },
        }));
        syncQueue();
      }}
    >
      <div>
        <strong className="mono small">{item.label}</strong>
        <div className="notice error small">{item.error}</div>
      </div>
      <div className="row-actions">
        <input type="number" min={0} inputMode="numeric" placeholder="Qty" aria-label="Quantity" value={quantity} onChange={(e) => setQuantity(e.target.value)} className="count-input" />
        <button className="btn small primary">Retry</button>
        <button type="button" className="btn small" onClick={() => window.confirm("Discard this scan?") && updateQueued(item.body.client_ref, () => null)}>
          Discard
        </button>
      </div>
    </form>
  );
}

function CountPanel({
  count,
  pending,
  onPendingChange,
  onAdd,
  onDiscard,
}: {
  count: StockCount | null;
  pending: { barcode: string; label: string; quantity: string } | null;
  onPendingChange: (p: { barcode: string; label: string; quantity: string }) => void;
  onAdd: () => void;
  onDiscard: () => void;
}) {
  if (!count || count.status !== "open") {
    return <p className="empty">Scan the shelf label of the location you want to count.</p>;
  }
  const counted = (count.rows ?? []).filter((r) => r.counted > 0);
  return (
    <>
      {pending && (
        <form
          className="card pending-card"
          onSubmit={(e) => {
            e.preventDefault();
            onAdd();
          }}
        >
          <h2>{pending.label}</h2>
          <Field
            label="Counted quantity"
            type="number"
            min={0}
            inputMode="numeric"
            value={pending.quantity}
            onChange={(e) => onPendingChange({ ...pending, quantity: e.target.value })}
            required
            autoFocus
          />
          <div className="row-actions">
            <button type="button" className="btn" onClick={onDiscard}>
              Discard
            </button>
            <button className="btn primary">Add to count</button>
          </div>
        </form>
      )}
      <section className="card">
        <div className="page-header">
          <h2>
            Counting {count.location.code} <span className="muted small">#{count.id}</span>
          </h2>
          <Link className="btn primary" to={`/counts/${count.id}`}>
            Review &amp; finish
          </Link>
        </div>
        {counted.length === 0 ? (
          <p className="muted">Nothing counted yet. Scan each item or pallet on this location.</p>
        ) : (
          <ul className="recent-list">
            {counted.map((r, i) => (
              <li key={i} className="recent-item">
                <div>
                  <strong>{r.product?.sku ?? `GTIN ${r.gtin}`}</strong>
                  <div className="muted small">
                    {[r.lot && `lot ${r.lot}`, r.expiry_date && `expires ${formatDate(r.expiry_date)}`, r.sscc && `SSCC ${r.sscc}`]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                </div>
                <strong className="mono">{r.counted}</strong>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function FoundList({ found }: { found: Found }) {
  const total = found.rows.reduce((sum, r) => sum + r.quantity, 0);
  return (
    <section className="card">
      <h2>{found.title}</h2>
      {found.rows.length === 0 ? (
        <p className="empty">Not in stock.</p>
      ) : (
        <>
          <ul className="recent-list">
            {found.rows.map((r, i) => (
              <li key={i} className="recent-item">
                <div>
                  <strong>
                    {r.quantity} × {r.product?.sku ?? `GTIN ${r.gtin}`}
                  </strong>
                  <div className="muted small">
                    {r.lot && `lot ${r.lot}`}
                    {r.expiry_date && ` · expires ${formatDate(r.expiry_date)}`}
                    {r.sscc && ` · SSCC ${r.sscc}`}
                  </div>
                </div>
                <strong className="mono">{r.location?.code ?? "no location"}</strong>
              </li>
            ))}
          </ul>
          <p className="muted small">Total: {total}</p>
        </>
      )}
    </section>
  );
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
  const isMove = pending.action === "move";
  const quantityRequired = pending.action === "receive" && !pending.offline;
  const title = {
    receive: "Receive",
    pick: "Pick",
    move: "Move — scan the destination location",
    log: "Log only",
  }[pending.action];

  return (
    <form
      className="card pending-card"
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
    >
      <h2>{title}</h2>
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
        {pending.action === "receive" ? (
          <Field
            label="SKU"
            value={pending.sku}
            onChange={(e) => onChange({ ...pending, sku: e.target.value })}
            readOnly={!!product}
            placeholder={product ? "" : "Optional; remembered for this GTIN"}
            hint={product?.name || undefined}
          />
        ) : (
          <Field label="SKU" value={product?.sku ?? "—"} readOnly hint={product?.name || undefined} />
        )}
        <Field
          label="Quantity"
          type="number"
          min={1}
          inputMode="numeric"
          value={pending.quantity}
          onChange={(e) => onChange({ ...pending, quantity: e.target.value })}
          required={quantityRequired}
          disabled={pending.action === "log"}
          placeholder={quantityRequired ? "" : "All"}
          hint={!quantityRequired && pending.action !== "log" ? "Leave empty to take everything (e.g. the whole pallet)." : undefined}
        />
        <div className="span-2">
          <Field label="Note" value={pending.note} onChange={(e) => onChange({ ...pending, note: e.target.value })} />
        </div>
      </div>
      <div className="row-actions">
        <button type="button" className="btn" onClick={onDiscard}>
          {isMove ? "Cancel move" : "Discard"}
        </button>
        {!isMove && (
          <button className="btn primary" disabled={busy}>
            {pending.action === "log" ? "Log only" : "Save"}
          </button>
        )}
      </div>
    </form>
  );
}
