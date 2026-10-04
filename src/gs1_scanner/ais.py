"""GS1 Application Identifier (AI) metadata used across the app."""

from __future__ import annotations

import re
from functools import cache

from biip import ParseError
from biip.checksums import gs1_standard_check_digit
from biip.gs1_application_identifiers import GS1ApplicationIdentifier

# AIs that get their own database column (everything else is kept in parsed_json).
AI_COLUMNS: dict[str, str] = {
    "00": "ai00_sscc",
    "01": "ai01_gtin",
    "02": "ai02_content_gtin",
    "10": "ai10_lot",
    "11": "ai11_prod_date",
    "15": "ai15_best_before",
    "17": "ai17_expiry",
    "21": "ai21_serial",
    "37": "ai37_qty",
    "240": "ai240_additional_id",
    "241": "ai241_customer_part",
}

# AIs whose last digit is a GS1 mod-10 check digit.
CHECK_DIGIT_AIS = frozenset({"00", "01", "02"})


@cache
def lookup(ai: str) -> GS1ApplicationIdentifier | None:
    """Return the official GS1 definition of ``ai``, or None if it is not a known AI."""
    try:
        found = GS1ApplicationIdentifier.extract(ai)
    except ParseError:
        return None
    return found if found.ai == ai else None


def title(ai: str) -> str:
    """Short human-readable name of an AI, e.g. ``BATCH/LOT``."""
    definition = lookup(ai)
    return definition.data_title if definition else "UNKNOWN AI"


def separator_required(ai: str) -> bool:
    """Whether a variable-length AI must be followed by FNC1 when not last in a barcode."""
    definition = lookup(ai)
    return definition.separator_required if definition else True


@cache
def _pattern(ai: str) -> re.Pattern[str] | None:
    definition = lookup(ai)
    return re.compile(definition.pattern) if definition else None


def matches_format(ai: str, value: str) -> bool:
    """Whether ``value`` has the length, character set and date format GS1 requires for ``ai``."""
    pattern = _pattern(ai)
    return pattern is None or pattern.fullmatch(ai + value) is not None


def check_digit_ok(ai: str, value: str) -> bool:
    """Whether the check digit of a GTIN/SSCC value is correct (True for other AIs)."""
    if ai not in CHECK_DIGIT_AIS or not value.isdigit() or len(value) < 2:
        return True
    return str(gs1_standard_check_digit(value[:-1])) == value[-1]
