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


def split_into_symbols(
    elements: Sequence[Element], max_chars: int = MAX_SYMBOL_CHARS
) -> list[list[Element]]:
    """Group elements into as few symbols as possible, each within ``max_chars``.

    Element order is kept. An element that alone exceeds the limit gets its own symbol.
    """
    symbols: list[list[Element]] = []
    current: list[Element] = []
    for e in elements:
        candidate = [*current, e]
        if current and len(encode_gs1_128(candidate)) - 1 > max_chars:
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


# --- Zebra (ZPL) labels for thermal printers ---
#
# Code128 symbols are encoded here (by ReportLab, as for the PDFs) and sent to
# the printer in ZPL's "no mode" with explicit subset switches and FNC1, so the
# printer draws exactly the symbol we computed instead of choosing its own.

_ZPL_START = {103: ">9", 104: ">:", 105: ">;"}  # start code A, B, C
_ZPL_SWITCH = {99: ("C", ">5"), 100: ("B", ">6"), 101: ("A", ">7")}
_ZPL_FNC1 = ">8"


def _zpl_escape(ch: str) -> str:
    # Field data uses ^FH with "_" as the hex escape; ">" starts invocation codes.
    if ch in "^~_":
        return f"_{ord(ch):02X}"
    return ">0" if ch == ">" else ch


def code128_zpl_data(value: str) -> tuple[str, int]:
    """ZPL field data for a Code128 symbol and its width in modules.

    ``value`` uses ReportLab's notation (FNC1 as "\\xf1").
    """
    symbol = Code128(value)
    symbol.validate()
    symbol.encode()
    codes = symbol.encoded[:-2]  # the printer adds the check digit and stop code
    modules = len(symbol.encoded) * 11 + 2  # stop code is 13 modules wide

    out = [_ZPL_START[codes[0]]]
    subset = {103: "A", 104: "B", 105: "C"}[codes[0]]
    for code in codes[1:]:
        if code == 102:
            out.append(_ZPL_FNC1)
        elif subset == "C" and code < 100:
            out.append(f"{code:02d}")
        elif code in _ZPL_SWITCH and not (subset == "B" and code == 100):
            subset, invocation = _ZPL_SWITCH[code]
            out.append(invocation)
        elif code < 64 or (subset == "B" and code < 96):
            out.append(_zpl_escape(chr(code + 32)))
        else:
            raise ValueError(f"Unsupported Code128 symbol value {code} in {value!r}")
    return "".join(out), modules


LABEL_SIZES_MM = {"4x6": (101.6, 152.4), "100x150": (100.0, 150.0)}
MIN_MODULE_DOTS = 2  # narrowest bar: 0.25 mm at 203 dpi, 0.17 mm at 300 dpi
LOCATION_LABEL_MM = (101.6, 50.8)  # 4 x 2 inch


# Font 0 is proportional; a character averages about half its height in width.
# A little more is allowed so text is never clipped at the label's edge.
_CHAR_WIDTH = 0.55
_MARGIN_MM = 5.0


def fit_text(text: str, height_mm: float, max_width_mm: float) -> str:
    """Shorten ``text`` (ending in "...") so it fits ``max_width_mm`` at this font size."""
    max_chars = int(max_width_mm / (height_mm * _CHAR_WIDTH))
    return text if len(text) <= max_chars else text[: max(max_chars - 3, 1)].rstrip() + "..."


class _Zpl:
    def __init__(self, dpi: int, width_mm: float):
        self.dpi = dpi
        self.width_mm = width_mm
        self.parts: list[str] = []

    def dots(self, mm_: float) -> int:
        return round(mm_ / 25.4 * self.dpi)

    def text(self, x_mm: float, y_mm: float, height_mm: float, text: str) -> None:
        """Draw one line of text, shortened if needed to stay on the label."""
        h = self.dots(height_mm)
        text = fit_text(text, height_mm, self.width_mm - x_mm - _MARGIN_MM)
        safe = "".join(_zpl_escape(c) if c in "^~_" else c for c in text)
        self.parts.append(f"^FO{self.dots(x_mm)},{self.dots(y_mm)}^A0N,{h},{h}^FH_^FD{safe}^FS")

    def barcode(
        self, x_mm: float, y_mm: float, value: str, height_mm: float, max_width_mm: float
    ) -> float:
        """Draw a Code128 symbol; returns its width in mm."""
        data, modules = code128_zpl_data(value)
        # Widest bars that fit; at least 1 dot. 2-3 dots ≈ 0.25-0.38 mm.
        module = max(1, min(4, self.dots(max_width_mm) // modules))
        self.parts.append(
            f"^BY{module}^FO{self.dots(x_mm)},{self.dots(y_mm)}"
            f"^BCN,{self.dots(height_mm)},N,N,N^FH_^FD{data}^FS"
        )
        return modules * module / self.dpi * 25.4

    def label(self, width_mm: float, height_mm: float) -> str:
        return (
            f"^XA^CI28^PW{self.dots(width_mm)}^LL{self.dots(height_mm)}"
            + "".join(self.parts)
            + "^XZ\n"
        )


def label_zpl(
    label: LabelData, *, title: str = "", subtitle: str = "", dpi: int = 203, size: str = "4x6"
) -> str:
    """A 4x6" (or 100x150 mm) logistics label with GS1-128 barcodes, as ZPL.

    ``title`` is printed large (e.g. the SKU), ``subtitle`` below it (e.g. the product name).
    """
    if not label.elements:
        raise ValueError("Nothing to print: the barcode has no GS1 data.")
    width, height = LABEL_SIZES_MM[size]
    z = _Zpl(dpi, width)
    margin = _MARGIN_MM
    y = margin
    z.text(margin, y, 9, title or label.sku or "GS1 label")
    y += 12
    if subtitle:
        z.text(margin, y, 6, subtitle)
        y += 8
    if label.location:
        z.text(margin, y, 6, f"Location: {label.location}")
        y += 8
    for e in label.elements:
        z.text(margin, y, 4.5, f"({e.ai}) {e.title}: {e.value}"[:60])
        y += 6
    y += 3
    # Barcodes from the bottom up, as on standard logistics labels. Use as
    # few symbols as possible while keeping bars at least MIN_MODULE_DOTS wide.
    usable = z.dots(width - 2 * margin)
    for max_chars in (MAX_SYMBOL_CHARS, 40, 32, 24, 16, 1):
        symbols = split_into_symbols(label.elements, max_chars)
        widest = max(code128_zpl_data(encode_gs1_128(sym))[1] for sym in symbols)
        if usable // widest >= MIN_MODULE_DOTS:
            break
    bar_h, hri_h, gap = 22.0, 4.0, 4.0
    bottom = height - margin
    for symbol in reversed(symbols):
        bottom -= hri_h
        # The human-readable line must be complete, so shrink it to fit rather than cut it.
        hri = "".join(e.hri for e in symbol)
        hri_size = min(hri_h - 0.5, (width - 2 * margin) / (len(hri) * _CHAR_WIDTH))
        z.text(margin, bottom + (hri_h - 0.5 - hri_size), hri_size, hri)
        bottom -= bar_h + 1
        z.barcode(margin, bottom, encode_gs1_128(symbol), bar_h, width - 2 * margin)
        bottom -= gap
    if bottom < y:
        raise ValueError("Too much data for one label.")
    return z.label(width, height)


def location_labels_zpl(locations: Sequence[LocationLabel], *, dpi: int = 203) -> str:
    """One 4x2" shelf label per location, as ZPL."""
    if not locations:
        raise ValueError("No locations to print.")
    width, height = LOCATION_LABEL_MM
    labels = []
    for loc in locations:
        z = _Zpl(dpi, width)
        data_width = z.barcode(0, 0, loc.code, 0, width - 10)  # measure only
        z.parts.clear()
        x = (width - data_width) / 2
        z.barcode(x, 4, loc.code, 22, width - 10)
        z.text(5, 30, 11, loc.code)
        if loc.description:
            z.text(5, 43, 4.5, loc.description[:50])
        labels.append(z.label(width, height))
    return "".join(labels)
