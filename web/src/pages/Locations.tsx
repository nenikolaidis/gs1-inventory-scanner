import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, errorMessage, withParams, type Location } from "../api";
import { useUser } from "../auth";
import { Empty, Field, Modal, Notice, PageHeader } from "../ui";

type Draft = Pick<Location, "code" | "warehouse" | "aisle" | "position" | "shelf" | "description">;
const EMPTY: Draft = { code: "", warehouse: "", aisle: "", position: "", shelf: "", description: "" };

export default function Locations() {
  const user = useUser();
  const isAdmin = user.role === "admin";
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [locations, setLocations] = useState<Location[]>([]);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<Location | "new" | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setLocations(await api.get<Location[]>("/api/locations", { q, include_inactive: showInactive }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [q, showInactive]);

  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);

  function toggle(id: number) {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  }

  const allChecked = locations.length > 0 && locations.every((l) => checked.has(l.id));
  const labelsUrl = withParams("/api/locations/labels.pdf", { ids: [...checked].join(",") });

  return (
    <>
      <PageHeader
        title="Locations"
        actions={
          <>
            <a
              className={`btn ${checked.size ? "" : "disabled"}`}
              href={checked.size ? labelsUrl : undefined}
              target="_blank"
              rel="noreferrer"
              aria-disabled={!checked.size}
            >
              Print labels{checked.size ? ` (${checked.size})` : ""}
            </a>
            {isAdmin && (
              <button className="btn primary" onClick={() => setEditing("new")}>
                Add location
              </button>
            )}
          </>
        }
      />
      <p className="muted">
        Print location labels and stick them on shelves. Scanning one on the scan screen sets the
        location for the pallets scanned after it. Labels fit A4 sheets of 2 × 7 (99.1 × 38.1 mm).
      </p>
      <div className="toolbar">
        <input type="search" className="search" placeholder="Search code, warehouse, description…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search locations" />
        <label className="toggle">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Show inactive
        </label>
      </div>
      {error && <Notice kind="error">{error}</Notice>}
      {locations.length === 0 ? (
        <Empty>No locations yet.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th className="check">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={allChecked}
                    onChange={() => setChecked(allChecked ? new Set() : new Set(locations.map((l) => l.id)))}
                  />
                </th>
                <th>Code</th>
                <th>Warehouse</th>
                <th>Aisle</th>
                <th>Position</th>
                <th>Shelf</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {locations.map((l) => (
                <tr key={l.id} className={l.is_active ? "" : "inactive"} onClick={isAdmin ? () => setEditing(l) : () => toggle(l.id)}>
                  <td className="check" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" aria-label={`Select ${l.code}`} checked={checked.has(l.id)} onChange={() => toggle(l.id)} />
                  </td>
                  <td data-label="Code" className="mono"><strong>{l.code}</strong>{!l.is_active && " (inactive)"}</td>
                  <td data-label="Warehouse">{l.warehouse || "—"}</td>
                  <td data-label="Aisle">{l.aisle || "—"}</td>
                  <td data-label="Position">{l.position || "—"}</td>
                  <td data-label="Shelf">{l.shelf || "—"}</td>
                  <td data-label="Description">{l.description || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <LocationForm
          location={editing === "new" ? null : editing}
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

function LocationForm({ location, onClose, onSaved }: { location: Location | null; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(location ?? EMPTY);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    const body: Draft = {
      code: draft.code,
      warehouse: draft.warehouse,
      aisle: draft.aisle,
      position: draft.position,
      shelf: draft.shelf,
      description: draft.description,
    };
    try {
      if (location) await api.patch(`/api/locations/${location.id}`, body);
      else await api.post("/api/locations", body);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function setActive(is_active: boolean) {
    if (!location) return;
    try {
      await api.patch(`/api/locations/${location.id}`, { is_active });
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  // Suggest a code from the parts while the user hasn't typed one.
  const suggested = [draft.warehouse, draft.aisle, draft.position, draft.shelf]
    .map((p) => p.trim().toUpperCase().replace(/[^A-Z0-9._/-]/g, ""))
    .filter(Boolean)
    .join("-");

  const set = (key: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [key]: e.target.value });

  return (
    <Modal
      title={location ? `Edit ${location.code}` : "Add location"}
      onClose={onClose}
      footer={
        <>
          {location && (
            <button type="button" className="btn" onClick={() => setActive(!location.is_active)}>
              {location.is_active ? "Deactivate" : "Reactivate"}
            </button>
          )}
          <button className="btn primary" form="location-form">
            Save
          </button>
        </>
      }
    >
      <form id="location-form" onSubmit={submit}>
        {error && <Notice kind="error">{error}</Notice>}
        <div className="form-grid">
          <Field label="Warehouse" value={draft.warehouse} onChange={set("warehouse")} autoFocus />
          <Field label="Aisle" value={draft.aisle} onChange={set("aisle")} />
          <Field label="Position" value={draft.position} onChange={set("position")} />
          <Field label="Shelf" value={draft.shelf} onChange={set("shelf")} />
        </div>
        <Field
          label="Code"
          value={draft.code}
          placeholder={suggested}
          onChange={set("code")}
          onFocus={() => !draft.code && suggested && setDraft({ ...draft, code: suggested })}
          hint="Printed on the shelf label. Letters, digits and . _ / - only."
          required
        />
        <Field label="Description" value={draft.description} onChange={set("description")} />
      </form>
    </Modal>
  );
}
