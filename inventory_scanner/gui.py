import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional
import os
import sys
import tempfile
import subprocess
from datetime import datetime
import tempfile
import subprocess
import os
import sys

from print_label import LabelData, make_label_pdf

from main import InventoryApp  # orchestrator


class AppWindow(tk.Tk):
    def __init__(self, app: InventoryApp):
        super().__init__()
        self.app = app

        self.title("Inventory Scanner (v1)")
        self.geometry("850x650")

        self._build_ui()

        self.last_parse = None

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

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
        ttk.Button(btn_row, text="Print", command=self.on_print).pack(side="right")

        frm_mid = ttk.LabelFrame(self, text="Parsed GS1 Data (auto-filled)")
        frm_mid.pack(fill="both", expand=True, **pad)

        self.parsed_text = tk.Text(frm_mid, height=10)
        self.parsed_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.parsed_text.configure(state="disabled")

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

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=12, pady=(0, 10))

    def _set_parsed_text(self, text: str):
        self.parsed_text.configure(state="normal")
        self.parsed_text.delete("1.0", "end")
        self.parsed_text.insert("1.0", text)
        self.parsed_text.configure(state="disabled")

    def _build_print_text(self) -> str:
        # Use what’s currently on screen
        barcode = (self.barcode_var.get() or "").strip()
        sku = (self.sku_var.get() or "").strip()
        wh = (self.wh_var.get() or "").strip()
        aisle = (self.aisle_var.get() or "").strip()
        pos = (self.pos_var.get() or "").strip()
        shelf = (self.shelf_var.get() or "").strip()

        parsed_display = ""
        if self.last_parse:
            parsed_display = self.app.format_parse_for_display(self.last_parse)

        lines = [
            "INVENTORY SCAN",
            f"Printed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "-" * 40,
            f"Barcode: {barcode}",
            "",
            "Parsed GS1:",
            parsed_display or "(not parsed)",
            "",
            "Manual fields:",
            f"SKU: {sku or '-'}",
            f"Warehouse: {wh or '-'}",
            f"Aisle: {aisle or '-'}",
            f"Position: {pos or '-'}",
            f"Shelf: {shelf or '-'}",
            "-" * 40,
        ]
        return "\n".join(lines)

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
            # Create temp PDF
            fd, pdf_path = tempfile.mkstemp(prefix="inventory_label_", suffix=".pdf")
            os.close(fd)

            make_label_pdf(label, pdf_path)

            # Send to printer
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
