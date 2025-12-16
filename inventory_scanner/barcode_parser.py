from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from functools import lru_cache


# Minimal GS1 AI rules needed for your supported list:
# - fixed length AIs: (00)=18n, (01)=14n, (02)=14n, (11)=6n
# - variable length AIs: (10) up to 20, (21) up to 20, (37) up to 8, (240) up to 30, (241) up to 30
# NOTE: raw scanner input without FNC1 separators can be ambiguous for variable-length fields.
# This implementation uses a "look-ahead for next known AI" approach.

FIXED_AIS: Dict[str, int] = {
    "00": 18,
    "01": 14,
    "02": 14,
    "11": 6,
}

VAR_AIS_MAX: Dict[str, int] = {
    "10": 20,
    "21": 20,
    "37": 8,
    "240": 30,
    "241": 30,
}

# We prefer matching longer AIs first (240/241 before 24 etc.)
KNOWN_AIS_SORTED = sorted(list(FIXED_AIS.keys()) + list(VAR_AIS_MAX.keys()), key=len, reverse=True)


@dataclass
class ParseResult:
    data: Dict[str, str]
    normalized_raw: str
    warnings: List[str]


def parse_barcode(barcode: str) -> ParseResult:
    s = (barcode or "").strip()
    if not s:
        return ParseResult(data={}, normalized_raw="", warnings=["Empty barcode input."])

    if "(" in s and ")" in s:
        return _parse_parentheses_format(s)

    # assume raw
    return _parse_raw_format(s)


def _parse_parentheses_format(s: str) -> ParseResult:
    i = 0
    out: Dict[str, str] = {}
    warnings: List[str] = []

    while i < len(s):
        if s[i] != "(":
            i += 1
            continue
        j = s.find(")", i + 1)
        if j == -1:
            warnings.append("Unclosed '(' found; stopped parsing.")
            break

        ai = s[i + 1 : j]
        i = j + 1  # move past ")"

        if ai in FIXED_AIS:
            n = FIXED_AIS[ai]
            value = s[i : i + n]
            if len(value) != n:
                warnings.append(f"AI({ai}) expected {n} chars, got {len(value)}.")
            out[ai] = value
            i += len(value)
        elif ai in VAR_AIS_MAX:
            # variable until next "(...)" or end
            next_ai_pos = s.find("(", i)
            value = s[i:] if next_ai_pos == -1 else s[i:next_ai_pos]
            if len(value) > VAR_AIS_MAX[ai]:
                warnings.append(f"AI({ai}) value longer than max {VAR_AIS_MAX[ai]}; truncating.")
                value = value[: VAR_AIS_MAX[ai]]
            out[ai] = value
            i = len(s) if next_ai_pos == -1 else next_ai_pos
        else:
            warnings.append(f"Unsupported AI({ai}) encountered; skipped.")
            # best effort: read until next "("
            next_ai_pos = s.find("(", i)
            i = len(s) if next_ai_pos == -1 else next_ai_pos

    return ParseResult(data=out, normalized_raw=_normalize_ai_dict_to_raw(out), warnings=warnings)


def _parse_raw_format(s: str) -> ParseResult:
    """
    Raw GS1 without separators is ambiguous for variable-length AIs.
    This version uses backtracking:
    - fixed AIs are deterministic
    - variable AIs try multiple cut points and pick the best parse
    """
    warnings: List[str] = []

    best = _parse_raw_backtrack(s)
    if best is None:
        return ParseResult(data={}, normalized_raw=s, warnings=["Could not parse raw input."])

    out, warn = best
    warnings.extend(warn)
    return ParseResult(data=out, normalized_raw=s, warnings=warnings)

def _match_ai_at(s: str, pos: int) -> Optional[str]:
    for ai in KNOWN_AIS_SORTED:
        if s.startswith(ai, pos):
            return ai
    return None
def _parse_raw_backtrack(s: str) -> Optional[Tuple[Dict[str, str], List[str]]]:
    """
    Backtracking parser for raw GS1 (no parentheses, no FNC1).

    Returns (data_dict, warnings) or None if parsing fails completely.
    """

    @lru_cache(maxsize=None)
    def parse_from(pos: int) -> Optional[Tuple[Dict[str, str], int, Tuple[str, ...]]]:
        # returns (data_dict, end_pos, warnings_tuple)
        if pos >= len(s):
            return ({}, pos, ())

        ai = _match_ai_at(s, pos)
        if not ai:
            return None

        p = pos + len(ai)

        # Fixed length AI
        if ai in FIXED_AIS:
            n = FIXED_AIS[ai]
            if p + n > len(s):
                return None

            val = s[p : p + n]
            rest = parse_from(p + n)
            if rest is None:
                return None

            d, end_pos, w = rest
            if ai in d:                 # <<< NEW: no duplicate AIs allowed
                return None
            out = dict(d)
            out[ai] = val
            return (out, end_pos, w)


        # Variable length AI -> try multiple cut points (backtracking)
        max_len = VAR_AIS_MAX[ai]
        end_limit = min(len(s), p + max_len)

        candidates: List[Tuple[Dict[str, str], int, Tuple[str, ...]]] = []
        
        # Heuristic: AI(37) (quantity) is numeric and often appears last.
        # If we are at the end of the barcode window, do NOT split inside it.
        if ai == "37" and end_limit == len(s):
            val = s[p:end_limit]
            if val:
                return ({ai: val}, end_limit, ())
            return None

        # Candidate: take to end (only if we truly reach end)
        if end_limit == len(s):
            val = s[p:end_limit]
            if val:  # <<< NEW: disallow empty variable values
                candidates.append(({ai: val}, end_limit, ()))

        # Candidates: cut where a known AI begins
        for cut in range(p + 1, end_limit + 1):
            if not _match_ai_at(s, cut):
                continue

            val = s[p:cut]
            if not val:  # <<< NEW: disallow empty variable values
                continue

            rest = parse_from(cut)
            if rest is None:
                continue

            d, end_pos, w = rest
            if ai in d:                 # <<< NEW: no duplicate AIs allowed
                continue
            out = dict(d)
            out[ai] = val
            candidates.append((out, end_pos, w))


        if not candidates:
            return None

        # NEW: stronger "best parse" scoring:
        # 1) consume farthest (end_pos)
        # 2) parse most fields
        # 3) prefer longer total values (helps choose correct variable-length splits)
        def score(item: Tuple[Dict[str, str], int, Tuple[str, ...]]) -> Tuple[int, int, int, int, int]:
            dct, end_pos, _w = item

            # prefer parses that include quantity
            has_37 = 1 if "37" in dct else 0

            # penalize AI(21) whose value looks like it starts with another AI (common false split)
            bad_21 = 0
            v21 = dct.get("21")
            if v21:
                if _match_ai_at(v21, 0) is not None:  # e.g., starts with "37"
                    bad_21 = 1

            total_len = sum(len(v) for v in dct.values())

            # order: consume farthest, most fields, has quantity, avoid bad_21, longer values
            return (end_pos, len(dct), has_37, -bad_21, total_len)


        candidates.sort(key=score, reverse=True)
        return candidates[0]

    result = parse_from(0)
    if result is None:
        return None

    data, end_pos, warn_tuple = result
    warnings = list(warn_tuple)

    if end_pos != len(s):
        warnings.append(f"Stopped early at position {end_pos} (len={len(s)}).")

    return data, warnings



def _normalize_ai_dict_to_raw(ai_dict: Dict[str, str]) -> str:
    # Not a perfect “original raw” reconstruction (order might differ),
    # but useful for debugging/storage.
    # Keep stable order: fixed then variable in KNOWN_AIS_SORTED order.
    parts = []
    for ai in KNOWN_AIS_SORTED:
        if ai in ai_dict:
            parts.append(ai + ai_dict[ai])
    return "".join(parts)
