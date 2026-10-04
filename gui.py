import tkinter as tk
from tkinter import ttk, messagebox
import os
import sys
import tempfile
import subprocess

from print_label import LabelData, make_label_pdf
from main import InventoryApp  # orchestrator


class AppWindow(tk.Tk):
    def __init__(self, app: InventoryApp):
        super().__init__()
        self.app = app

        self.title("Inventory Scanner (v1)")
        self.geometry("850x650")

        self.last_parse = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # --- Top: Scan ---
        frm_top = ttk.LabelFrame(self, text="Scan / Enter Barcode")
        frm_top.pack(fill="x", **pad)

        self.barcode_var = tk.StringVar()
        self.barcode_entry = ttk.Entry(frm_top, textvariable=self.barcode_var, font=("Arial", 12))
        self.barcode_entry.pack(fill="x", padx=10, pady=8)
        self.barcode_entry.focus_set()

        btn_row = ttk.Frame(frm_top)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Button(btn_row, text="Parse", command=self.on_parse).pack(side="left")
        ttk.Button(btn_row, text="Clear", command=self.on_clear).pack(side="left", padx=8)
        ttk.Button(btn_row, text="Open Search & Records", command=self.open_search_window).pack(side="right", padx=8)
        ttk.Button(btn_row, text="Print", command=self.on_print).pack(side="right")

        # --- Middle: Parsed output ---
        frm_mid = ttk.LabelFrame(self, text="Parsed GS1 Data (auto-filled)")
        frm_mid.pack(fill="both", expand=True, **pad)

        self.parsed_text = tk.Text(frm_mid, height=10)
        self.parsed_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.parsed_text.configure(state="disabled")

        # --- Bottom: Manual fields ---
        frm_bot = ttk.LabelFrame(self, text="Manual Fields")
        frm_bot.pack(fill="x", **pad)

        self.sku_var = tk.StringVar()
        self.wh_var = tk.StringVar()
        self.aisle_var = tk.StringVar()
        self.pos_var = tk.StringVar()
        self.shelf_var = tk.StringVar()

        grid = ttk.Frame(frm_bot)
        grid.pack(fill="x", padx=10, pady=10)
        grid.columnconfigure(1, weight=1)

        def add_row(r, label, var):
            ttk.Label(grid, text=label, width=16).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=4)
            ttk.Entry(grid, textvariable=var).grid(row=r, column=1, sticky="ew", pady=4)

        add_row(0, "SKU (5–6):", self.sku_var)
        add_row(1, "Warehouse:", self.wh_var)
        add_row(2, "Aisle:", self.aisle_var)
        add_row(3, "Position:", self.pos_var)
        add_row(4, "Shelf:", self.shelf_var)

        ttk.Button(frm_bot, text="Save Record", command=self.on_save).pack(anchor="e", padx=10, pady=(0, 10))

        # --- Status ---
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=12, pady=(0, 10))

    def _set_parsed_text(self, text: str):
        self.parsed_text.configure(state="normal")
        self.parsed_text.delete("1.0", "end")
        self.parsed_text.insert("1.0", text)
        self.parsed_text.configure(state="disabled")

    def on_parse(self):
        raw = self.barcode_var.get().strip()
        self.last_parse = self.app.parse(raw)

        display = self.app.format_parse_for_display(self.last_parse)
        self._set_parsed_text(display)
        self.status_var.set("Parsed.")

    def on_save(self):
        if not self.last_parse:
            messagebox.showerror("Error", "Parse a barcode first.")
            return

        try:
            rec = self.app.build_record(
                raw_barcode=self.barcode_var.get(),
                parsed=self.last_parse,
                sku=self.sku_var.get(),
                warehouse=self.wh_var.get(),
                aisle=self.aisle_var.get(),
                position=self.pos_var.get(),
                shelf=self.shelf_var.get(),
            )
            new_id = self.app.save_record(rec)
        except ValueError as e:
            messagebox.showerror("Validation error", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error", f"Could not save record:\n{e}")
            return

        self.status_var.set(f"Saved record #{new_id}.")
        messagebox.showinfo("Saved", f"Record saved with ID #{new_id}.")
        self.on_clear()

    def on_print(self):
        if not self.last_parse:
            messagebox.showerror("Error", "Parse a barcode first.")
            return

        raw = (self.barcode_var.get() or "").strip()
        if not raw:
            messagebox.showerror("Error", "Barcode is empty.")
            return

        parsed_display = self.app.format_parse_for_display(self.last_parse)

        label = LabelData(
            raw_barcode=raw,
            parsed_text=parsed_display,
            sku=(self.sku_var.get() or "").strip(),
            warehouse=(self.wh_var.get() or "").strip(),
            aisle=(self.aisle_var.get() or "").strip(),
            position=(self.pos_var.get() or "").strip(),
            shelf=(self.shelf_var.get() or "").strip(),
        )

        try:
            fd, pdf_path = tempfile.mkstemp(prefix="inventory_label_", suffix=".pdf")
            os.close(fd)

            make_label_pdf(label, pdf_path)

            if sys.platform.startswith("win"):
                os.startfile(pdf_path, "print")  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["lp", pdf_path], check=True)
            else:
                subprocess.run(["lpr", pdf_path], check=True)

            self.status_var.set("Sent label to printer.")
            messagebox.showinfo("Print", "Sent barcode label to printer.")
        except Exception as e:
            messagebox.showerror("Print failed", str(e))

    def open_search_window(self):
        win = tk.Toplevel(self)
        win.title("Search / View Records")
        win.geometry("900x420")

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=10)

        search_var = tk.StringVar()
        ttk.Label(top, text="Search:").pack(side="left")

        entry = ttk.Entry(top, textvariable=search_var)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        entry.focus_set()

        btns = ttk.Frame(top)
        btns.pack(side="right")

        results_list = tk.Listbox(win, height=14)
        results_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        state = {"rows": []}

        def do_search():
            q = (search_var.get() or "").strip()
            try:
                rows = self.app.search_records(q, limit=100)
            except Exception as e:
                messagebox.showerror("Search failed", str(e), parent=win)
                return

            state["rows"] = rows
            results_list.delete(0, tk.END)

            if not rows:
                results_list.insert(tk.END, "(no results)")
                return

            for r in rows:
                rid = r.get("id")
                sku = r.get("sku") or "-"
                wh = r.get("warehouse") or "-"
                gtin = r.get("ai01_gtin") or r.get("ai02_content_gtin") or "-"
                lot = r.get("ai10_lot") or "-"
                qty = r.get("ai37_qty") or "-"
                created = r.get("created_at") or "-"
                results_list.insert(
                    tk.END,
                    f"#{rid} | {created} | SKU:{sku} | WH:{wh} | GTIN:{gtin} | LOT:{lot} | QTY:{qty}"
                )

        def _get_selected_record_id() -> int | None:
            rows = state["rows"]
            if not rows:
                return None
            sel = results_list.curselection()
            if not sel:
                return None
            row = rows[sel[0]]
            rid = row.get("id")
            return int(rid) if rid is not None else None

        def view_selected():
            rid = _get_selected_record_id()
            if rid is None:
                messagebox.showinfo("View", "Select a record first.", parent=win)
                return

            full = self.app.get_record(rid)
            if not full:
                messagebox.showerror("View", f"Record #{rid} not found.", parent=win)
                return

            lines = []
            lines.append(f"Record ID: {full.get('id')}")
            lines.append(f"Created: {full.get('created_at')}")
            lines.append("")
            lines.append(f"Barcode: {full.get('raw_barcode') or '-'}")
            lines.append("")
            lines.append("GS1 Fields:")
            for k in [
                "ai00_sscc","ai01_gtin","ai02_content_gtin","ai10_lot","ai11_prod_date",
                "ai21_serial","ai37_qty","ai240_additional_id","ai241_customer_part"
            ]:
                lines.append(f"  {k}: {full.get(k) or '-'}")
            lines.append("")
            lines.append("Location / SKU:")
            for k in ["sku","warehouse","aisle","position","shelf"]:
                lines.append(f"  {k}: {full.get(k) or '-'}")

            messagebox.showinfo("Record Details", "\n".join(lines), parent=win)

        def load_selected_into_form():
            rid = _get_selected_record_id()
            if rid is None:
                messagebox.showinfo("Load", "Select a record first.", parent=win)
                return

            full = self.app.get_record(rid)
            if not full:
                messagebox.showerror("Load", f"Record #{rid} not found.", parent=win)
                return

            # Fill main form fields
            self.barcode_var.set(full.get("raw_barcode") or "")
            self.sku_var.set(full.get("sku") or "")
            self.wh_var.set(full.get("warehouse") or "")
            self.aisle_var.set(full.get("aisle") or "")
            self.pos_var.set(full.get("position") or "")
            self.shelf_var.set(full.get("shelf") or "")

            # Re-parse for printing/preview
            raw = (full.get("raw_barcode") or "").strip()
            self.last_parse = self.app.parse(raw) if raw else None
            self._set_parsed_text(self.app.format_parse_for_display(self.last_parse) if self.last_parse else "")

            self.status_var.set(f"Loaded record #{rid} into form.")
            win.destroy()

        ttk.Button(btns, text="Search", command=do_search).pack(side="left")
        ttk.Button(btns, text="View Selected", command=view_selected).pack(side="left", padx=8)
        ttk.Button(btns, text="Load Into Form", command=load_selected_into_form).pack(side="left")

        entry.bind("<Return>", lambda _e: do_search())
        results_list.bind("<Double-Button-1>", lambda _e: view_selected())

        do_search()

    def on_clear(self):
        self.barcode_var.set("")
        self._set_parsed_text("")
        self.sku_var.set("")
        self.wh_var.set("")
        self.aisle_var.set("")
        self.pos_var.set("")
        self.shelf_var.set("")
        self.last_parse = None
        self.status_var.set("Cleared.")
        self.barcode_entry.focus_set()

    def on_close(self):
        try:
            self.app.close()
        finally:
            self.destroy()


def run(app: InventoryApp):
    win = AppWindow(app)
    win.mainloop()
