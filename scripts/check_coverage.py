"""
Verify per-module coverage thresholds.

Reads coverage.xml (produced by pytest --cov-report=xml) and checks that
specific modules meet their minimum coverage. Used in CI to enforce
"core.py and schemas.py must be ≥ 80% covered" without forcing a global
threshold that would punish less-critical code.

Usage:
    python scripts/check_coverage.py \
        --module tijuana_dispersion/core.py --min 80 \
        --module tijuana_dispersion/schemas.py --min 80
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_coverage_xml(path: Path) -> dict[str, float]:
    """Return {filename: line-rate-percent} from coverage.xml."""
    tree = ET.parse(path)
    root = tree.getroot()
    out: dict[str, float] = {}
    for cls in root.iter("class"):
        filename = cls.get("filename")
        line_rate = cls.get("line-rate")
        if filename and line_rate is not None:
            out[filename] = float(line_rate) * 100.0
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-xml", type=Path, default=Path("coverage.xml"))
    parser.add_argument(
        "--module",
        action="append",
        required=True,
        help="filename (e.g. tijuana_dispersion/core.py)",
    )
    parser.add_argument(
        "--min",
        action="append",
        required=True,
        type=float,
        help="minimum percent coverage for the corresponding --module",
    )
    args = parser.parse_args()

    if len(args.module) != len(args.min):
        print("error: --module and --min must be paired", file=sys.stderr)
        return 2

    if not args.coverage_xml.exists():
        print(
            f"error: {args.coverage_xml} not found; " f"did pytest run with --cov-report=xml?",
            file=sys.stderr,
        )
        return 2

    rates = parse_coverage_xml(args.coverage_xml)
    failed = False
    for module, threshold in zip(args.module, args.min, strict=True):
        actual = rates.get(module)
        if actual is None:
            print(f"✗ {module}: not found in coverage report", file=sys.stderr)
            failed = True
            continue
        status = "✓" if actual >= threshold else "✗"
        print(f"  {status} {module}: {actual:.1f}% (min {threshold:.0f}%)")
        if actual < threshold:
            failed = True

    if failed:
        print("\ncoverage check failed", file=sys.stderr)
        return 1
    print("\ncoverage check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
