from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Any, Optional

# --- Make imports work when running from /tests ---
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from barcode_parser import parse_barcode  # noqa: E402


@dataclass
class Case:
    name: str
    barcode: str
    expected: Dict[str, str]   # expected AI -> value (keys like "02", "10", "00", ...)
    kind: str                  # "human" or "raw"


def make_human(ai_map: Dict[str, str], order: List[str]) -> str:
    # "(02)....(11)....(10)...."
    return "".join([f"({ai}){ai_map[ai]}" for ai in order])


def make_raw(ai_map: Dict[str, str], order: List[str]) -> str:
    # "02....11....10...."
    return "".join([f"{ai}{ai_map[ai]}" for ai in order])


def build_50_cases() -> List[Case]:
    # Base example you gave
    base = {
        "02": "38033432662426",
        "11": "250319",
        "10": "0090167063",
        "00": "380334329001623191",
        "37": "000360",
    }

    # Different valid orders (important for real-world scanners)
    orders = [
        ["02", "11", "10", "00", "37"],  # your example
        ["00", "02", "11", "10", "37"],
        ["02", "00", "11", "10", "37"],
        ["02", "11", "00", "10", "37"],
        ["02", "11", "10", "37", "00"],
    ]

    cases: List[Case] = []

    # 25 human-readable tests
    for i in range(25):
        ai_map = dict(base)

        # Deterministic variations
        ai_map["10"] = f"{9000000000 + i}"          # lot changes length slightly
        ai_map["37"] = f"{(i * 7) % 999999:06d}"    # 6 digits qty (still numeric and variable)
        # keep fixed-length AIs correct:
        # 02 GTIN-14, 11 YYMMDD, 00 SSCC-18
        # vary GTIN last digits
        ai_map["02"] = base["02"][:-3] + f"{i:03d}"
        ai_map["00"] = base["00"][:-3] + f"{(100 + i):03d}"

        order = orders[i % len(orders)]
        barcode = make_human(ai_map, order)

        cases.append(
            Case(
                name=f"HUMAN_{i+1:02d}_order_{''.join(order)}",
                barcode=barcode,
                expected={k: ai_map[k] for k in order},
                kind="human",
            )
        )

    # 25 raw tests
    # NOTE: raw parsing without FNC1 separators can be ambiguous for variable-length AIs,
    # so we keep AI sequences unambiguous by ensuring a known AI follows each variable field.
    for i in range(25):
        ai_map = dict(base)

        ai_map["10"] = f"{8000000000 + i}"          # lot changes
        ai_map["37"] = f"{(i * 13) % 99999999:08d}" # up to 8 digits qty
        ai_map["02"] = base["02"][:-4] + f"{i:04d}"
        ai_map["00"] = base["00"][:-4] + f"{(2000 + i):04d}"

        order = orders[i % len(orders)]
        barcode = make_raw(ai_map, order)

        cases.append(
            Case(
                name=f"RAW_{i+1:02d}_order_{''.join(order)}",
                barcode=barcode,
                expected={k: ai_map[k] for k in order},
                kind="raw",
            )
        )

    # Total: 50
    return cases


def run_tests() -> int:
    cases = build_50_cases()

    failures: List[Dict[str, Any]] = []
    passed = 0

    for c in cases:
        try:
            res = parse_barcode(c.barcode)
            got = res.data or {}

            # Compare only expected keys (ignore extra keys if parser returns more in future)
            mismatch: Dict[str, Any] = {}
            for ai, exp_val in c.expected.items():
                got_val = got.get(ai)
                if got_val != exp_val:
                    mismatch[ai] = {"expected": exp_val, "got": got_val}

            if mismatch:
                failures.append(
                    {
                        "name": c.name,
                        "kind": c.kind,
                        "barcode": c.barcode,
                        "expected": c.expected,
                        "got": got,
                        "mismatch": mismatch,
                        "warnings": res.warnings,
                    }
                )
            else:
                passed += 1

        except Exception as e:
            failures.append(
                {
                    "name": c.name,
                    "kind": c.kind,
                    "barcode": c.barcode,
                    "expected": c.expected,
                    "error": repr(e),
                }
            )

    report = {
        "total": len(cases),
        "passed": passed,
        "failed": len(failures),
        "failures": failures,
    }

    out_path = os.path.join(HERE, "parsing_test_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Total={report['total']} Passed={report['passed']} Failed={report['failed']}")
    print(f"Failure report written to: {out_path}")

    # Print quick summary to terminal
    if failures:
        print("\nFailed cases:")
        for fx in failures[:20]:
            print(f" - {fx['name']}")
        if len(failures) > 20:
            print(f" ... and {len(failures) - 20} more (see JSON report).")

    # Return non-zero exit code if failures exist (useful in CI)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
