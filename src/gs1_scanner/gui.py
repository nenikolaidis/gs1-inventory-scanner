"""Tkinter front end."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from gs1_scanner import paths
from gs1_scanner.ais import title
from gs1_scanner.gs1 import ParseResult
from gs1_scanner.labels import LabelData, make_label_pdf
from gs1_scanner.models import InventoryRecord
from gs1_scanner.service import InventoryService

LABEL_RETENTION_SECONDS = 7 * 24 * 3600


class AppWindow(tk.Tk):
    def __init__(self, service: InventoryService):
        super().__init__()
        self.service = service
        self.title("GS1 Inventory Scanner")
        self.geometry("860x680")
        self.minsize(640, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}

        # --- Scan ---
        frm_scan = ttk.LabelFrame(self, text="Scan or type a barcode, then press Enter")
        frm_scan.pack(fill="x", **pad)

        self.barcode_var = tk.StringVar()
        self.barcode_entry = ttk.Entry(frm_scan, textvariable=self.barcode_var, font=("Arial", 12))
        self.barcode_entry.pack(fill="x", padx=10, pady=8)
        self.barcode_entry.bind("<Return>", lambda _e: self.on_parse(move_focus=True))
        self.barcode_entry.focus_set()

        btn_row = ttk.Frame(frm_scan)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btn_row, text="Parse", command=self.on_parse).pack(side="left")
        ttk.Button(btn_row, text="Clear", command=self.on_clear).pack(side="left", padx=8)
        ttk.Button(btn_row, text="Search Records…", command=self.open_search_window).pack(
            side="right"
        )
        ttk.Button(btn_row, text="Print Label…", command=self.on_print).pack(side="right", padx=8)

        # --- Parsed elements ---
        frm_parsed = ttk.LabelFrame(self, text="GS1 data")
        frm_parsed.pack(fill="both", expand=True, **pad)

        self.parsed_tree = ttk.Treeview(
            frm_parsed, columns=("ai", "name", "value"), show="headings", height=7
        )
        for col, heading, width in [
            ("ai", "AI", 60),
            ("name", "Name", 200),
            ("value", "Value", 400),
        ]:
            self.parsed_tree.heading(col, text=heading, anchor="w")
            self.parsed_tree.column(col, width=width, stretch=(col == "value"), anchor="w")
        self.parsed_tree.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        self.warnings_var = tk.StringVar()
        ttk.Label(
            frm_parsed, textvariable=self.warnings_var, foreground="#b45309", wraplength=780
        ).pack(fill="x", padx=10, pady=(0, 8))

        # --- Manual fields ---
        frm_manual = ttk.LabelFrame(self, text="SKU and location")
        frm_manual.pack(fill="x", **pad)

        grid = ttk.Frame(frm_manual)
        grid.pack(fill="x", padx=10, pady=10)
        grid.columnconfigure(1, weight=1)

        self.field_vars: dict[str, tk.StringVar] = {}
        self.field_entries: dict[str, ttk.Entry] = {}
        labels = [
            ("sku", "SKU (5–6 chars):"),
            ("warehouse", "Warehouse:"),
            ("aisle", "Aisle:"),
            ("position", "Position:"),
            ("shelf", "Shelf:"),
        ]
        for row, (name, text) in enumerate(labels):
            var = tk.StringVar()
            ttk.Label(grid, text=text, width=16).grid(row=row, column=0, sticky="w", pady=3)
            entry = ttk.Entry(grid, textvariable=var)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self.field_vars[name] = var
            self.field_entries[name] = entry
        self.field_entries["shelf"].bind("<Return>", lambda _e: self.on_save())

        ttk.Button(frm_manual, text="Save Record", command=self.on_save).pack(
            anchor="e", padx=10, pady=(0, 10)
        )

        # --- Status ---
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=12, pady=(0, 10))

    # --- helpers ---

    def _show_parse(self, parsed: ParseResult | None) -> None:
        self.parsed_tree.delete(*self.parsed_tree.get_children())
        if parsed is None:
            self.warnings_var.set("")
            return
        for e in parsed.elements:
            self.parsed_tree.insert("", "end", values=(e.ai, e.title, e.value))
        self.warnings_var.set("\n".join(f"⚠ {w}" for w in parsed.warnings))

    def _fields(self) -> dict[str, str]:
        return {name: var.get() for name, var in self.field_vars.items()}

    # --- actions ---

    def on_parse(self, move_focus: bool = False) -> ParseResult:
        parsed = self.service.parse(self.barcode_var.get())
        self._show_parse(parsed)
        if parsed.elements:
            self.status_var.set(f"Parsed {len(parsed.elements)} field(s).")
            if move_focus:
                self.field_entries["sku"].focus_set()
        else:
            self.status_var.set("Nothing parsed.")
        return parsed

    def on_save(self) -> None:
        # Always parse what is in the box now, so the saved fields match the saved barcode.
        self.on_parse()
        try:
            record = self.service.build_record(self.barcode_var.get(), **self._fields())
            new_id = self.service.save(record)
        except ValueError as e:
            messagebox.showerror("Cannot save", str(e), parent=self)
            return
        except Exception as e:
            messagebox.showerror("Error", f"Could not save record:\n{e}", parent=self)
            return
        self.on_clear()
        self.status_var.set(f"Saved record #{new_id}.")

    def on_print(self) -> None:
        parsed = self.on_parse()
        if not parsed.elements:
            messagebox.showerror("Print", "Scan or type a barcode first.", parent=self)
            return
        label = LabelData(
            elements=parsed.elements, **{k: v.strip() for k, v in self._fields().items()}
        )
        try:
            out_dir = paths.labels_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
            _delete_old_labels(out_dir)
            pdf = make_label_pdf(label, out_dir / f"label-{datetime.now():%Y%m%d-%H%M%S}.pdf")
            _open_file(pdf)
        except Exception as e:
            messagebox.showerror("Print failed", str(e), parent=self)
            return
        self.status_var.set(f"Label opened for printing: {pdf}")

    def on_clear(self) -> None:
        self.barcode_var.set("")
        for var in self.field_vars.values():
            var.set("")
        self._show_parse(None)
        self.status_var.set("Cleared.")
        self.barcode_entry.focus_set()

    def load_record(self, record: InventoryRecord) -> None:
        self.barcode_var.set(record.raw_barcode)
        for name, var in self.field_vars.items():
            var.set(getattr(record, name) or "")
        self.on_parse()
        self.status_var.set(f"Loaded record #{record.id} into the form.")

    def open_search_window(self) -> None:
        SearchWindow(self)


class SearchWindow(tk.Toplevel):
    COLUMNS = [
        ("id", "#", 50),
        ("created", "Created (UTC)", 160),
        ("sku", "SKU", 80),
        ("warehouse", "Warehouse", 100),
        ("gtin", "GTIN", 140),
        ("lot", "Lot", 120),
        ("qty", "Qty", 70),
    ]

    def __init__(self, main: AppWindow):
        super().__init__(main)
        self.main = main
        self.service = main.service
        self.title("Search Records")
        self.geometry("900x440")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Label(top, text="Search:").pack(side="left")
        self.query_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.query_var)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.bind("<Return>", lambda _e: self.do_search())
        entry.focus_set()
        ttk.Button(top, text="Search", command=self.do_search).pack(side="left")

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=10)
        self.tree = ttk.Treeview(frm, columns=[c for c, _, _ in self.COLUMNS], show="headings")
        for col, heading, width in self.COLUMNS:
            self.tree.heading(col, text=heading, anchor="w")
            self.tree.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(frm, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-Button-1>", lambda _e: self.view_selected())

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=10)
        ttk.Button(btns, text="View", command=self.view_selected).pack(side="left")
        ttk.Button(btns, text="Load Into Form", command=self.load_selected).pack(
            side="left", padx=8
        )
        ttk.Button(btns, text="Delete", command=self.delete_selected).pack(side="right")

        self.do_search()

    def do_search(self) -> None:
        try:
            records = self.service.search(self.query_var.get(), limit=200)
        except Exception as e:
            messagebox.showerror("Search failed", str(e), parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        for r in records:
            e = r.elements
            self.tree.insert(
                "",
                "end",
                iid=str(r.id),
                values=(
                    r.id,
                    r.created_at,
                    r.sku or "",
                    r.warehouse or "",
                    e.get("01") or e.get("02") or "",
                    e.get("10") or "",
                    e.get("37") or "",
                ),
            )

    def _selected(self) -> InventoryRecord | None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Records", "Select a record first.", parent=self)
            return None
        record = self.service.get(int(selection[0]))
        if record is None:
            messagebox.showerror("Records", "That record no longer exists.", parent=self)
            self.do_search()
        return record

    def view_selected(self) -> None:
        record = self._selected()
        if record is None:
            return
        lines = [
            f"Record #{record.id}, created {record.created_at} (UTC)",
            "",
            f"Scanned: {record.raw_barcode}",
            "",
            "GS1 data:",
            *(f"  ({ai}) {title(ai)}: {value}" for ai, value in record.elements.items()),
            "",
            f"SKU: {record.sku or '-'}",
            f"Warehouse: {record.warehouse or '-'}",
            f"Aisle: {record.aisle or '-'}",
            f"Position: {record.position or '-'}",
            f"Shelf: {record.shelf or '-'}",
        ]
        messagebox.showinfo("Record details", "\n".join(lines), parent=self)

    def load_selected(self) -> None:
        record = self._selected()
        if record is None:
            return
        self.main.load_record(record)
        self.destroy()

    def delete_selected(self) -> None:
        record = self._selected()
        if record is None:
            return
        if messagebox.askyesno(
            "Delete record", f"Delete record #{record.id}? This cannot be undone.", parent=self
        ):
            self.service.delete(record.id)
            self.do_search()


def _open_file(path: Path) -> None:
    """Open a file in the system's default app (the PDF viewer prints it)."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def _delete_old_labels(directory: Path) -> None:
    cutoff = time.time() - LABEL_RETENTION_SECONDS
    for pdf in directory.glob("label-*.pdf"):
        try:
            if pdf.stat().st_mtime < cutoff:
                pdf.unlink()
        except OSError:
            pass


def run(service: InventoryService) -> None:
    AppWindow(service).mainloop()
