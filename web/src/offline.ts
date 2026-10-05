// Offline support for the scan screen: scans made without a connection are
// queued on this device and uploaded when the connection is back. Each scan
// carries a unique reference, so an upload that is retried is saved only once.

import { useEffect, useState } from "react";

import { ApiError, api, type Location, type Scan } from "./api";

export interface ScanBody {
  barcode: string;
  action: string;
  location_id: number | null;
  to_location_id: number | null;
  sku: string | null;
  quantity: number | null;
  note: string;
  client_ref: string;
}

export interface QueuedScan {
  body: ScanBody;
  label: string; // what the operator saw, e.g. "Receive (01)0301… into A1"
  queuedAt: string;
  error?: string; // set when the server refused it; needs the operator
}

const QUEUE_KEY = "scan.queue";
const LOCATIONS_KEY = "cache.locations";
const CHANGED = "scan-queue-changed";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage full or blocked: nothing more we can do offline
  }
}

export function newRef(): string {
  // crypto.randomUUID needs a secure context; fall back for plain-HTTP trials.
  if (typeof crypto !== "undefined" && "randomUUID" in crypto && window.isSecureContext) {
    return crypto.randomUUID();
  }
  const rand = Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0"));
  return `${Date.now().toString(36)}-${rand.join("")}`;
}

/** True when a request failed because there is no connection (not a server error). */
export function isOffline(e: unknown): boolean {
  return !(e instanceof ApiError) && (e instanceof TypeError || !navigator.onLine);
}

export function queued(): QueuedScan[] {
  return read<QueuedScan[]>(QUEUE_KEY, []);
}

function setQueue(items: QueuedScan[]) {
  write(QUEUE_KEY, items);
  window.dispatchEvent(new Event(CHANGED));
}

export function enqueue(body: ScanBody, label: string) {
  setQueue([...queued(), { body, label, queuedAt: new Date().toISOString() }]);
}

export function updateQueued(ref: string, change: (item: QueuedScan) => QueuedScan | null) {
  setQueue(
    queued()
      .map((item) => (item.body.client_ref === ref ? change(item) : item))
      .filter((item): item is QueuedScan => item !== null),
  );
}

let syncing: Promise<number> | null = null;

/** Upload queued scans in order. Returns how many were uploaded. */
export function syncQueue(onSaved?: (scan: Scan) => void): Promise<number> {
  syncing ??= (async () => {
    let sent = 0;
    try {
      for (const item of queued()) {
        if (item.error) continue; // waiting for the operator to fix it
        try {
          const scan = await api.post<Scan>("/api/scans", item.body);
          updateQueued(item.body.client_ref, () => null);
          onSaved?.(scan);
          sent += 1;
        } catch (e) {
          if (isOffline(e)) break; // still offline; try again later
          const message = e instanceof Error ? e.message : String(e);
          updateQueued(item.body.client_ref, (it) => ({ ...it, error: message }));
        }
      }
    } finally {
      syncing = null;
    }
    return sent;
  })();
  return syncing;
}

export function useQueue(): QueuedScan[] {
  const [items, setItems] = useState(queued);
  useEffect(() => {
    const update = () => setItems(queued());
    window.addEventListener(CHANGED, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(CHANGED, update);
      window.removeEventListener("storage", update);
    };
  }, []);
  return items;
}

// --- locations, cached so shelf labels can be recognised offline ---

export async function refreshLocationCache() {
  try {
    write(LOCATIONS_KEY, await api.get<Location[]>("/api/locations"));
  } catch {
    // keep the old cache
  }
}

export function cachedLocation(code: string): Location | null {
  const wanted = code.trim().toUpperCase();
  return read<Location[]>(LOCATIONS_KEY, []).find((l) => l.code === wanted) ?? null;
}
