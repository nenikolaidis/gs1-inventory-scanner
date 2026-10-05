"""Turn scanned or typed barcode text into GS1 elements.

Input forms, and who parses them:

* Human-readable, ``(01)0301...(10)LOT1``: split here, each field checked
  against biip's GS1 format rules (invalid values are kept and flagged).
* Raw with FNC1/GS separators (``\\x1d``), optionally prefixed with a
  symbology identifier like ``]C1``: biip.
* Raw without separators (what most keyboard-wedge scanners produce):
  :mod:`gs1_scanner.raw_parser`, which handles the ambiguity explicitly.
* A plain EAN/UPC/GTIN number: stored as AI (01).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from biip import ParseError
from biip.gs1_messages import GS1Message

from gs1_scanner import ais
from gs1_scanner.raw_parser import parse_raw

GS = "\x1d"
_SYMBOLOGY_ID = re.compile(r"^\][A-Za-z][0-9]")
_HRI_AI = re.compile(r"\((\d{2,4})\)")
_MAX_ALTERNATIVES_SHOWN = 3


@dataclass(frozen=True)
class Element:
    ai: str
    value: str

    @property
    def title(self) -> str:
        return ais.title(self.ai)

    @property
    def hri(self) -> str:
        return f"({self.ai}){self.value}"


@dataclass(frozen=True)
class ParseResult:
    elements: tuple[Element, ...]
    warnings: tuple[str, ...] = ()

    @property
    def data(self) -> dict[str, str]:
        """AI -> value. If an AI repeats, the first occurrence wins."""
        out: dict[str, str] = {}
        for e in self.elements:
            out.setdefault(e.ai, e.value)
        return out

    @property
    def hri(self) -> str:
        """Human-readable form, e.g. ``(01)03012345678900(10)LOT1``."""
        return "".join(e.hri for e in self.elements)


def parse_barcode(text: str) -> ParseResult:
    s = (text or "").strip()
    if not s:
        return ParseResult((), ("Empty barcode input.",))

    if s.startswith("("):
        return _parse_hri(s)

    s = _SYMBOLOGY_ID.sub("", s, count=1)
    if GS in s:
        return _parse_separated(s)
    return _parse_unseparated(s)


def _parse_hri(s: str) -> ParseResult:
    # Not biip's GS1Message.parse_hri: it only keeps \w characters, so it
    # silently truncates valid values like lot "A-B" or serial "SN.1".
    elements = _split_hri(s)
    if not elements:
        return ParseResult((), ("Could not parse barcode: no (AI) found.",))
    return _finish(elements)


def _split_hri(s: str) -> list[Element]:
    # re.split with a capture group gives [prefix, ai, value, ai, value, ...]
    parts = _HRI_AI.split(s)
    return [Element(ai, value) for ai, value in zip(parts[1::2], parts[2::2], strict=True)]


def _parse_separated(s: str) -> ParseResult:
    try:
        message = GS1Message.parse(s)
        return _finish([Element(es.ai.ai, es.value) for es in message.element_strings])
    except ParseError as e:
        biip_error = str(e)

    # Fall back to the raw parser per segment: each segment's only ambiguity
    # is where its last field ends, which the separator already tells us.
    elements: list[Element] = []
    warnings: list[str] = []
    for segment in filter(None, s.split(GS)):
        result = _parse_unseparated(segment)
        if not result.elements:
            return ParseResult((), (f"Could not parse barcode: {biip_error}",))
        elements.extend(result.elements)
        warnings.extend(result.warnings)
    return ParseResult(tuple(elements), tuple(warnings))


def _parse_unseparated(s: str) -> ParseResult:
    parsed = parse_raw(s)
    if parsed is None:
        if s.isdigit() and len(s) in (8, 12, 13, 14):
            return _finish(
                [Element("01", s.zfill(14))], ["Read as a plain GTIN (no GS1 AIs found)."]
            )
        return ParseResult((), ("Could not parse barcode: no known GS1 AIs found.",))

    warnings: list[str] = []
    if parsed.alternatives:
        shown = parsed.alternatives[:_MAX_ALTERNATIVES_SHOWN]
        others = "; ".join("".join(f"({ai}){v}" for ai, v in alt) for alt in shown)
        more = len(parsed.alternatives) - len(shown)
        warnings.append(
            "Ambiguous barcode (no FNC1 separators); check the values. "
            f"It could also be: {others}" + (f" (+{more} more)" if more > 0 else "")
        )
    return _finish([Element(ai, v) for ai, v in parsed.elements], warnings)


def _finish(elements: list[Element], warnings: list[str] | None = None) -> ParseResult:
    warnings = list(warnings or [])
    for e in elements:
        if ais.lookup(e.ai) is None:
            warnings.append(f"AI ({e.ai}) is not a GS1 Application Identifier.")
        elif not ais.matches_format(e.ai, e.value):
            warnings.append(f"AI ({e.ai}) value {e.value!r} does not match the GS1 format.")
        elif not ais.check_digit_ok(e.ai, e.value):
            warnings.append(f"AI ({e.ai}) value {e.value} has a wrong check digit.")
    return ParseResult(tuple(elements), tuple(warnings))
