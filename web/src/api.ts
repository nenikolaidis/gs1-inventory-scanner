// Typed client for the GS1 Scanner JSON API (see src/gs1_scanner/server).

export type Role = "admin" | "operator";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface Product {
  id: number;
  sku: string;
  gtin: string | null;
  name: string;
}

export interface Location {
  id: number;
  code: string;
  warehouse: string;
  aisle: string;
  position: string;
  shelf: string;
  description: string;
  is_active: boolean;
}

export interface Element {
  ai: string;
  title: string;
  value: string;
}

export interface Parse {
  elements: Element[];
  warnings: string[];
  hri: string;
}

export interface Resolved {
  kind: "location" | "gs1" | "unknown";
  location: Location | null;
  parse: Parse | null;
  product: Product | null;
}

export interface Scan {
  id: number;
  created_at: string;
  user: { id: number; display_name: string } | null;
  location: Location | null;
  product: Product | null;
  raw_barcode: string;
  gs1_hri: string;
  elements: Element[];
  warnings: string[];
  sku: string | null;
  gtin: string | null;
  sscc: string | null;
  lot: string | null;
  serial: string | null;
  quantity: number | null;
  production_date: string | null;
  best_before: string | null;
  expiry_date: string | null;
  note: string;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// Called when any request comes back 401, so the app can show the login screen.
let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

type Params = Record<string, string | number | boolean | null | undefined>;

export function withParams(path: string, params?: Params): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      "X-Requested-With": "gs1-scanner",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/api/auth/login")) onUnauthorized();
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) message = data.detail[0].msg;
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(res.status, message);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>("GET", withParams(path, params)),
  post: <T>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  delete: (path: string) => request<void>("DELETE", path),
};

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
