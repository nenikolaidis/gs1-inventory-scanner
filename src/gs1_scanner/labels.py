"""PDF labels with GS1-128 barcodes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from gs1_scanner import ais
from gs1_scanner.gs1 import Element

FNC1 = "\xf1"  # how ReportLab's Code128 spells the FNC1 function character
MAX_SYMBOL_CHARS = 48  # GS1 limit on data characters in one GS1-128 symbol
X_DIMENSION = 0.33 * mm  # narrowest bar width


@dataclass(frozen=True)
class LabelData:
    elements: Sequence[Element]
    sku: str = ""
    warehouse: str = ""
    aisle: str = ""
    position: str = ""
    shelf: str = ""


def encode_gs1_128(elements: Sequence[Element]) -> str:
    """Code128 input for one GS1-128 symbol: leading FNC1, plus FNC1 after
    variable-length fields that are not last."""
    out = [FNC1]
    for i, e in enumerate(elements):
        out.append(e.ai + e.value)
        if i < len(elements) - 1 and ais.separator_required(e.ai):
            out.append(FNC1)
    return "".join(out)


def split_into_symbols(elements: Sequence[Element]) -> list[list[Element]]:
    """Group elements into as few symbols as possible, each within the GS1 length limit.

    Element order is kept. An element that alone exceeds the limit gets its own symbol.
    """
    symbols: list[list[Element]] = []
    current: list[Element] = []
    for e in elements:
        candidate = [*current, e]
        if current and len(encode_gs1_128(candidate)) - 1 > MAX_SYMBOL_CHARS:
            symbols.append(current)
            candidate = [e]
        current = candidate
    if current:
        symbols.append(current)
    return symbols


def make_label_pdf(label: LabelData, out_path: str | Path) -> Path:
    if not label.elements:
        raise ValueError("Nothing to print: the barcode has no GS1 data.")

    out_path = Path(out_path).resolve()
    c = canvas.Canvas(str(out_path), pagesize=A4)
    page_w, page_h = A4
    x0 = 18 * mm
    usable_w = page_w - 2 * x0
    y = page_h - 20 * mm

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x0, y, "INVENTORY LABEL")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    c.drawString(x0, y, f"Printed: {datetime.now():%Y-%m-%d %H:%M}")
    y -= 10 * mm

    for symbol in split_into_symbols(label.elements):
        barcode = Code128(encode_gs1_128(symbol), barHeight=18 * mm, barWidth=X_DIMENSION)
        if barcode.width > usable_w:  # shrink rather than run off the page
            barcode = Code128(
                encode_gs1_128(symbol),
                barHeight=18 * mm,
                barWidth=X_DIMENSION * usable_w / barcode.width,
            )
        y -= barcode.height
        barcode.drawOn(c, x0, y)
        y -= 5 * mm
        c.setFont("Helvetica", 10)
        c.drawString(x0 + barcode.lquiet, y, "".join(e.hri for e in symbol))
        y -= 10 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, "Location")
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    for name, value in [
        ("SKU", label.sku),
        ("Warehouse", label.warehouse),
        ("Aisle", label.aisle),
        ("Position", label.position),
        ("Shelf", label.shelf),
    ]:
        c.drawString(x0, y, f"{name}: {value or '-'}")
        y -= 6 * mm
    y -= 4 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(x0, y, "GS1 data")
    y -= 6 * mm
    c.setFont("Courier", 9)
    for e in label.elements:
        if y < 20 * mm:
            c.showPage()
            y = page_h - 20 * mm
            c.setFont("Courier", 9)
        c.drawString(x0, y, f"({e.ai}) {e.title}: {e.value}"[:110])
        y -= 4.5 * mm

    c.showPage()
    c.save()
    return out_path
