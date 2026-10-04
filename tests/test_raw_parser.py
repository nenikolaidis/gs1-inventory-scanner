from __future__ import annotations

import time

from gs1_scanner.raw_parser import parse_raw


def test_rejects_input_that_cannot_be_fully_read() -> None:
    assert parse_raw("10" + "A" * 25) is None  # lot longer than 20 chars
    assert parse_raw("99ABC") is None  # AI outside the supported set
    assert parse_raw("0103012345") is None  # GTIN too short


def test_rejects_invalid_dates() -> None:
    # Month 13 is impossible, so (17) can't end here and the input is unreadable.
    assert parse_raw("17251301") is None
    assert parse_raw("17251231").elements == (("17", "251231"),)


def test_prefers_correct_check_digits() -> None:
    # Lot "1" + SSCC vs a longer lot: only the first gives a valid SSCC check digit.
    parsed = parse_raw("101" + "00380334329001623191")
    assert parsed.elements == (("10", "1"), ("00", "380334329001623191"))


def test_no_duplicate_ais() -> None:
    parsed = parse_raw("10AB10CD")
    assert parsed.elements == (("10", "AB10CD"),)


def test_pathological_input_is_fast() -> None:
    start = time.perf_counter()
    parse_raw("10" + "1037" * 5 + "21" + "10" * 10 + "37" + "1" * 8)
    assert time.perf_counter() - start < 1.0
