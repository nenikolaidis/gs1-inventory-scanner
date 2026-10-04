"""PDF labels with GS1-128 barcodes."""

from __future__ import annotations

import io
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
    location: str = ""
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
    out_path = Path(out_path).resolve()
    out_path.write_bytes(label_pdf_bytes(label))
    return out_path


def label_pdf_bytes(label: LabelData) -> bytes:
    if not label.elements:
        raise ValueError("Nothing to print: the barcode has no GS1 data.")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
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
        ("Location", label.location),
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
    return buf.getvalue()


@dataclass(frozen=True)
class LocationLabel:
    code: str
    description: str = ""


# Shelf labels: a 2 x 7 grid on A4, matching common 99.1 x 38.1 mm label sheets.
SHEET_COLUMNS, SHEET_ROWS = 2, 7
SHEET_LABEL_W, SHEET_LABEL_H = 99.1 * mm, 38.1 * mm
SHEET_MARGIN_X, SHEET_MARGIN_Y, SHEET_GAP_X = 4.65 * mm, 15.15 * mm, 2.5 * mm


def location_labels_pdf(locations: Sequence[LocationLabel]) -> bytes:
    """A4 sheets of shelf labels, each with a Code128 barcode of the location code."""
    if not locations:
        raise ValueError("No locations to print.")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, page_h = A4
    per_page = SHEET_COLUMNS * SHEET_ROWS
    for i, loc in enumerate(locations):
        if i and i % per_page == 0:
            c.showPage()
        row, col = divmod(i % per_page, SHEET_COLUMNS)
        x = SHEET_MARGIN_X + col * (SHEET_LABEL_W + SHEET_GAP_X)
        top = page_h - SHEET_MARGIN_Y - row * SHEET_LABEL_H
        inner_w = SHEET_LABEL_W - 10 * mm

        barcode = Code128(loc.code, barHeight=14 * mm, barWidth=X_DIMENSION)
        if barcode.width > inner_w:
            barcode = Code128(
                loc.code, barHeight=14 * mm, barWidth=X_DIMENSION * inner_w / barcode.width
            )
        barcode.drawOn(c, x + (SHEET_LABEL_W - barcode.width) / 2, top - 4 * mm - barcode.height)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(x + SHEET_LABEL_W / 2, top - 25 * mm, loc.code)
        if loc.description:
            c.setFont("Helvetica", 9)
            c.drawCentredString(x + SHEET_LABEL_W / 2, top - 31 * mm, loc.description[:60])
    c.showPage()
    c.save()
    return buf.getvalue()
