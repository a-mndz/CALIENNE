#!/usr/bin/env python
"""Gate G4 — dependency pinning check (blocking, zero-API).

Exits nonzero unless ``requirements.lock`` exists and every pinned package in
it carries at least one ``--hash`` line. This is the pip secure-installs
contract: "Hashes are required for all requirements" — an unhased lockfile
can be silently substituted by a compromised index.

Usage: python tools/check_pins.py [--lock requirements.lock]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LOCK_DEFAULT = Path(__file__).resolve().parents[1] / "requirements.lock"

_REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=LOCK_DEFAULT)
    args = parser.parse_args(argv)

    if not args.lock.is_file():
        print(f"G4 FAIL: {args.lock} not found — generate it with "
              "'uv pip compile requirements.txt -o requirements.lock --generate-hashes'")
        return 1

    errors: list[str] = []
    packages = 0
    hashed_packages = 0
    current: str | None = None
    current_hashed = False

    def _flush() -> None:
        nonlocal packages, hashed_packages, current, current_hashed
        if current is not None:
            packages += 1
            if current_hashed:
                hashed_packages += 1
            else:
                errors.append(f"{current}: pinned without --hash")
        current, current_hashed = None, False

    for line in args.lock.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\\").strip()
        if not line or line.startswith("#"):
            continue
        match = _REQUIREMENT_RE.match(line)
        if match:
            _flush()
            current = match.group(1)
        elif line.startswith("--hash=") and current is not None:
            current_hashed = True
    _flush()

    if packages == 0:
        errors.append("no pinned requirements found in lockfile")

    if errors:
        print("G4 FAIL:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"G4 passed: {hashed_packages}/{packages} pinned packages hashed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
