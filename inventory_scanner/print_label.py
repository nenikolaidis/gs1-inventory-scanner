# print_label.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.graphics.barcode import code128


@dataclass
class LabelData:
    raw_barcode: str
    parsed_text: str
    sku: str = ""
    warehouse: str = ""
    aisle: str = ""
    position: str = ""
    shelf: str = ""


def make_label_pdf(label: LabelData, out_path: str) -> str:
    """
    Creates a single-page PDF with a scannable Code128 barcode + text details.
    Returns the output path.
    """
    out_path = str(Path(out_path).resolve())

    c = canvas.Canvas(out_path, pagesize=A4)
    page_w, page_h = A4

    # Margins / layout
    x0 = 18 * mm
    y = page_h - 20 * mm

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x0, y, "INVENTORY SCAN LABEL")
    y -= 8 * mm

    c.setFont("Helvetica", 9)
    c.drawString(x0, y, f"Printed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    y -= 10 * mm

    # Barcode (Code128)
    # barHeight controls how tall the barcode is; humanReadable shows text under barcode
    bc = code128.Code128(label.raw_barcode, barHeight=22 * mm, humanReadable=True)
    bc_x = x0
    bc_y = y - 25 * mm
    bc.drawOn(c, bc_x, bc_y)
    y = bc_y - 10 * mm

    # Manual fields
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, "Manual fields")
    y -= 6 * mm

    c.setFont("Helvetica", 10)
    c.drawString(x0, y, f"SKU: {label.sku or '-'}")
    y -= 6 * mm
    c.drawString(x0, y, f"Warehouse: {label.warehouse or '-'}")
    y -= 6 * mm
    c.drawString(x0, y, f"Aisle: {label.aisle or '-'}")
    y -= 6 * mm
    c.drawString(x0, y, f"Position: {label.position or '-'}")
    y -= 6 * mm
    c.drawString(x0, y, f"Shelf: {label.shelf or '-'}")
    y -= 10 * mm

    # Parsed GS1 (multi-line)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, "Parsed GS1")
    y -= 6 * mm

    c.setFont("Courier", 9)
    for line in (label.parsed_text or "(not parsed)").splitlines():
        if y < 20 * mm:
            c.showPage()
            y = page_h - 20 * mm
            c.setFont("Courier", 9)
        c.drawString(x0, y, line[:140])
        y -= 4.5 * mm

    c.showPage()
    c.save()
    return out_path
