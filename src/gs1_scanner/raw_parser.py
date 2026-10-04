"""Parse raw GS1 element strings that arrive without FNC1 separators.

Many keyboard-wedge scanners drop the invisible FNC1/GS character, so a
variable-length field (lot, serial, quantity, ...) has no marked end. The input
is then ambiguous: ``10ABC2112`` can be lot ``ABC2112``, or lot ``ABC``
followed by serial ``12``.

This parser only considers a small set of AIs common on logistics labels,
enumerates every complete reading of the input, drops readings that break GS1
format rules (e.g. a non-numeric quantity or month 13), and ranks the rest.
When several readings rank equally, the caller gets the others as
``alternatives`` so the user can be warned.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from gs1_scanner import ais

FIXED_LENGTH: dict[str, int] = {"00": 18, "01": 14, "02": 14, "11": 6, "15": 6, "17": 6}
MAX_LENGTH: dict[str, int] = {"10": 20, "21": 20, "37": 8, "240": 30, "241": 30}
SUPPORTED_AIS = sorted([*FIXED_LENGTH, *MAX_LENGTH], key=len, reverse=True)

# Stop enumerating after this many readings to keep pathological input fast.
MAX_READINGS = 2000

Reading = tuple[tuple[str, str], ...]  # ((ai, value), ...) in scan order


@dataclass(frozen=True)
class RawParse:
    elements: Reading
    alternatives: tuple[Reading, ...]


def parse_raw(s: str) -> RawParse | None:
    """Return the most plausible reading of ``s``, or None if no reading uses all of it."""
    readings = _all_readings(s)
    if not readings:
        return None
    ranked = sorted(readings, key=_rank)
    best = ranked[0]
    tied = tuple(r for r in ranked[1:] if _rank(r)[:2] == _rank(best)[:2])
    return RawParse(elements=best, alternatives=tied)


def _all_readings(s: str) -> tuple[Reading, ...]:
    @cache
    def readings_from(pos: int, used: frozenset[str]) -> tuple[Reading, ...]:
        if pos == len(s):
            return ((),)
        found: list[Reading] = []
        for ai in SUPPORTED_AIS:
            if ai in used or not s.startswith(ai, pos):
                continue
            start = pos + len(ai)
            if ai in FIXED_LENGTH:
                ends = range(start + FIXED_LENGTH[ai], start + FIXED_LENGTH[ai] + 1)
            else:
                ends = range(start + 1, start + MAX_LENGTH[ai] + 1)
            for end in ends:
                if end > len(s):
                    break
                value = s[start:end]
                if not ais.matches_format(ai, value):
                    continue
                for rest in readings_from(end, used | {ai}):
                    found.append(((ai, value), *rest))
                    if len(found) >= MAX_READINGS:
                        return tuple(found)
        return tuple(found)

    return readings_from(0, frozenset())


def _rank(reading: Reading) -> tuple[int, int, tuple[int, ...]]:
    """Sort key, lower is better.

    1. fewer wrong check digits;
    2. more fields, because a separate AI hiding inside a lot or serial is
       more likely than a lot that happens to contain a valid AI + value;
    3. longer values earlier, i.e. don't cut a field short when a later
       field could absorb the difference.
    """
    bad_check_digits = sum(not ais.check_digit_ok(ai, value) for ai, value in reading)
    return (bad_check_digits, -len(reading), tuple(-len(value) for _, value in reading))
