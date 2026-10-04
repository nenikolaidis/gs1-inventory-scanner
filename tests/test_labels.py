from __future__ import annotations

from pathlib import Path

import pytest

from gs1_scanner.gs1 import parse_barcode
from gs1_scanner.labels import (
    FNC1,
    MAX_SYMBOL_CHARS,
    LabelData,
    encode_gs1_128,
    make_label_pdf,
    split_into_symbols,
)

SAMPLE = "(02)38033432662426(11)250319(10)0090167063(00)380334329001623191(37)000360"


def test_fnc1_only_after_variable_length_fields() -> None:
    elements = parse_barcode("(01)03012345678902(10)LOT1(17)261231(21)SN1").elements
    assert encode_gs1_128(elements) == (f"{FNC1}010301234567890210LOT1{FNC1}1726123121SN1")


def test_long_data_is_split_into_valid_symbols() -> None:
    elements = parse_barcode(SAMPLE).elements
    symbols = split_into_symbols(elements)
    assert len(symbols) == 2
    assert [e for s in symbols for e in s] == list(elements)
    for s in symbols:
        assert len(encode_gs1_128(s)) - 1 <= MAX_SYMBOL_CHARS


def test_make_label_pdf(tmp_path: Path) -> None:
    out = make_label_pdf(
        LabelData(elements=parse_barcode(SAMPLE).elements, sku="ABC12"), tmp_path / "l.pdf"
    )
    assert out.read_bytes().startswith(b"%PDF")


def test_empty_label_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make_label_pdf(LabelData(elements=()), tmp_path / "l.pdf")
