from __future__ import annotations

import pytest
from biip.checksums import gs1_standard_check_digit

from gs1_scanner.gs1 import GS, parse_barcode

SAMPLE_HRI = "(02)38033432662426(11)250319(10)0090167063(00)380334329001623191(37)000360"
SAMPLE_RAW = "0238033432662426112503191000901670630038033432900162319137000360"
SAMPLE_DATA = {
    "02": "38033432662426",
    "11": "250319",
    "10": "0090167063",
    "00": "380334329001623191",
    "37": "000360",
}


def with_check_digit(payload: str) -> str:
    return payload + str(gs1_standard_check_digit(payload))


def generated_cases() -> list[tuple[str, dict[str, str]]]:
    """The original 50 regression cases: the sample barcode in five AI orders,
    with varying values, as human-readable and as raw (no separators) input."""
    orders = [
        ["02", "11", "10", "00", "37"],
        ["00", "02", "11", "10", "37"],
        ["02", "00", "11", "10", "37"],
        ["02", "11", "00", "10", "37"],
        ["02", "11", "10", "37", "00"],
    ]
    cases = []
    for i in range(25):
        data = dict(SAMPLE_DATA)
        data["10"] = str(9000000000 + i)
        data["37"] = f"{(i * 7) % 999999:06d}"
        data["02"] = with_check_digit(SAMPLE_DATA["02"][:-4] + f"{i:03d}")
        data["00"] = with_check_digit(SAMPLE_DATA["00"][:-4] + f"{100 + i:03d}")
        order = orders[i % len(orders)]
        cases.append(("".join(f"({ai}){data[ai]}" for ai in order), {ai: data[ai] for ai in order}))
    for i in range(25):
        data = dict(SAMPLE_DATA)
        data["10"] = str(8000000000 + i)
        data["37"] = f"{(i * 13) % 99999999:08d}"
        data["02"] = with_check_digit(SAMPLE_DATA["02"][:-5] + f"{i:04d}")
        data["00"] = with_check_digit(SAMPLE_DATA["00"][:-5] + f"{2000 + i:04d}")
        order = orders[i % len(orders)]
        cases.append(("".join(f"{ai}{data[ai]}" for ai in order), {ai: data[ai] for ai in order}))
    return cases


@pytest.mark.parametrize(("barcode", "expected"), generated_cases())
def test_generated_cases(barcode: str, expected: dict[str, str]) -> None:
    result = parse_barcode(barcode)
    assert result.data == expected
    assert list(result.data) == list(expected)  # scan order is kept
    if barcode.startswith("("):
        assert result.warnings == ()
    else:
        # Some raw cases are genuinely ambiguous (e.g. lot 8000000021 + qty 00000273
        # also reads as lot 80000000 + serial 3700000273); those must say so.
        assert all(w.startswith("Ambiguous") for w in result.warnings)


@pytest.mark.parametrize("barcode", [SAMPLE_HRI, SAMPLE_RAW])
def test_sample(barcode: str) -> None:
    result = parse_barcode(barcode)
    assert result.data == SAMPLE_DATA
    assert result.hri == SAMPLE_HRI
    assert result.warnings == ()


def test_empty() -> None:
    assert parse_barcode("  ").warnings == ("Empty barcode input.",)


def test_fnc1_separated_with_symbology_identifier() -> None:
    result = parse_barcode(f"]C1010301234567890210LOT1{GS}21SN1012{GS}3712")
    assert result.data == {"01": "03012345678902", "10": "LOT1", "21": "SN1012", "37": "12"}
    assert result.warnings == ()


def test_symbology_identifier_without_separators_uses_raw_parser() -> None:
    result = parse_barcode("]C1010301234567890210LOT1")
    assert result.data == {"01": "03012345678902", "10": "LOT1"}


def test_any_gs1_ai_works_with_separators() -> None:
    result = parse_barcode(f"010301234567890217261231{GS}400PO-123")
    assert result.data == {"01": "03012345678902", "17": "261231", "400": "PO-123"}


def test_serial_containing_10_is_not_lost() -> None:
    result = parse_barcode("010301234567890210LOT121SN10123712")
    assert result.data == {"01": "03012345678902", "10": "LOT1", "21": "SN1012", "37": "12"}


def test_quantity_must_be_numeric() -> None:
    result = parse_barcode("01030123456789023710010ABC")
    assert result.data == {"01": "03012345678902", "37": "100", "10": "ABC"}


def test_ambiguous_raw_input_is_flagged() -> None:
    result = parse_barcode("0238033432662426371210LOT99")
    assert result.data == {"02": "38033432662426", "37": "12", "10": "LOT99"}
    assert len(result.warnings) == 1
    assert "Ambiguous" in result.warnings[0]
    assert "(37)1(21)0LOT99" in result.warnings[0]


def test_wrong_check_digit_is_a_warning_not_an_error() -> None:
    result = parse_barcode("(01)03012345678901")
    assert result.data == {"01": "03012345678901"}
    assert result.warnings == ("AI (01) value 03012345678901 has a wrong check digit.",)


def test_invalid_hri_keeps_the_values_and_flags_them() -> None:
    result = parse_barcode("(01)123(10)X")
    assert result.data == {"01": "123", "10": "X"}
    assert result.warnings == ("AI (01) value '123' does not match the GS1 format.",)


@pytest.mark.parametrize("value", ["A-B", "AB.CD", "A/B", "LOT_1", "SN-1", "A+B%C"])
def test_hri_keeps_punctuation_in_values(value: str) -> None:
    # Regression: biip's parse_hri silently truncated these at the punctuation.
    result = parse_barcode(f"(01)03012345678902(10){value}(21){value}")
    assert result.data == {"01": "03012345678902", "10": value, "21": value}
    assert result.warnings == ()


def test_separated_input_keeps_punctuation() -> None:
    result = parse_barcode(f"010301234567890210A-B.C/D{GS}21SN-1")
    assert result.data == {"01": "03012345678902", "10": "A-B.C/D", "21": "SN-1"}


def test_plain_ean13_is_stored_as_gtin() -> None:
    result = parse_barcode("4006381333931")
    assert result.data == {"01": "04006381333931"}


def test_garbage_input() -> None:
    result = parse_barcode("hello world")
    assert result.elements == ()
    assert "Could not parse" in result.warnings[0]
