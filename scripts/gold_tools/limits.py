"""Re-derive value and limits from each record's printed text and compare them with the gold file.

The arithmetic is done in decimal from `raw`, so a typo in a stored number or a wrong sign shows up
as a mismatch. Exits non-zero if any record disagrees or a toleranced record cannot be parsed.

    uv run python scripts/gold_tools/limits.py nist_ctc_01_asme1_rd
"""

import argparse
import sys
from decimal import Decimal

from common import load_gold
from resourcly.callout_values import TOLERANCED, derive


def same(stored, derived):
    if stored is None or derived is None:
        return stored is None and derived is None
    if isinstance(derived, list):
        return (
            isinstance(stored, list)
            and len(stored) == len(derived)
            and all(same(s, d) for s, d in zip(stored, derived, strict=True))
        )
    return abs(Decimal(str(stored)) - derived) < Decimal("1e-9")


def check(record):
    """Return a problem description, or None when the stored value and limits match raw."""
    derived = derive(record)
    if derived is None:
        return (
            "cannot parse a toleranced value from raw"
            if record["tolerance_style"] in TOLERANCED
            else None
        )
    value, limits = derived
    stored_limits = record["limits"]
    if not same(record["value"], value):
        return f"value {record['value']} but raw gives {value}"
    if (stored_limits is None) != (limits is None) or (
        limits
        and not (
            same(stored_limits["lower"], limits[0]) and same(stored_limits["upper"], limits[1])
        )
    ):
        return f"limits {stored_limits} but raw gives {limits}"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stem", help="drawing PDF stem, e.g. nist_ctc_01_asme1_rd")
    args = parser.parse_args()

    problems = 0
    for record in load_gold(args.stem)["values"]:
        if record["callout"] not in ("dimension", "feature_control_frame"):
            continue
        problem = check(record)
        problems += problem is not None
        limits = record["limits"]
        shown = f"[{limits['lower']}, {limits['upper']}]" if limits else "-"
        print(
            f"{'MISMATCH' if problem else 'ok':8} {record['id']:10} {record['raw']:32} {shown}"
            + (f"  ({problem})" if problem else "")
        )
    print(f"{problems} mismatches")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
