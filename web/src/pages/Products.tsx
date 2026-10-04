import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, errorMessage, type Product } from "../api";
import { useUser } from "../auth";
import { Empty, Field, Modal, Notice, PageHeader } from "../ui";

type Draft = { sku: string; gtin: string; name: string };
const EMPTY: Draft = { sku: "", gtin: "", name: "" };

export default function Products() {
  const user = useUser();
  const isAdmin = user.role === "admin";
  const [q, setQ] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [editing, setEditing] = useState<Product | "new" | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (query: string) => {
    try {
      setProducts(await api.get<Product[]>("/api/products", { q: query }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(q), 200);
    return () => clearTimeout(t);
  }, [q, load]);

  return (
    <>
      <PageHeader
        title="Products"
        actions={
          isAdmin && (
            <button className="btn primary" onClick={() => setEditing("new")}>
              Add product
            </button>
          )
        }
      />
      <p className="muted">
        Products link a GS1 GTIN to your SKU, so scans fill in the SKU automatically. They're also
        created when someone types a SKU for an unknown GTIN on the scan screen.
      </p>
      <input type="search" className="search" placeholder="Search SKU, GTIN or name…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search products" />
      {error && <Notice kind="error">{error}</Notice>}
      {products.length === 0 ? (
        <Empty>No products yet.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>GTIN</th>
                <th>Name</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id} onClick={isAdmin ? () => setEditing(p) : undefined} className={isAdmin ? "" : "static"}>
                  <td data-label="SKU"><strong>{p.sku}</strong></td>
                  <td data-label="GTIN" className="mono">{p.gtin ?? "—"}</td>
                  <td data-label="Name">{p.name || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <ProductForm
          product={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load(q);
          }}
        />
      )}
    </>
  );
}

function ProductForm({ product, onClose, onSaved }: { product: Product | null; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(
    product ? { sku: product.sku, gtin: product.gtin ?? "", name: product.name } : EMPTY,
  );
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body = { ...draft, gtin: draft.gtin.trim() || null };
    try {
      if (product) await api.patch(`/api/products/${product.id}`, body);
      else await api.post("/api/products", body);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove() {
    if (!product || !window.confirm(`Delete product ${product.sku}?`)) return;
    try {
      await api.delete(`/api/products/${product.id}`);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const set = (key: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [key]: e.target.value });

  return (
    <Modal
      title={product ? `Edit ${product.sku}` : "Add product"}
      onClose={onClose}
      footer={
        <>
          {product && (
            <button type="button" className="btn danger" onClick={remove}>
              Delete
            </button>
          )}
          <button className="btn primary" form="product-form">
            Save
          </button>
        </>
      }
    >
      <form id="product-form" onSubmit={submit}>
        {error && <Notice kind="error">{error}</Notice>}
        <Field label="SKU" value={draft.sku} onChange={set("sku")} required autoFocus />
        <Field label="GTIN" value={draft.gtin} onChange={set("gtin")} inputMode="numeric" hint="8, 12, 13 or 14 digits. Leave empty if unknown." />
        <Field label="Name" value={draft.name} onChange={set("name")} />
      </form>
    </Modal>
  );
}
