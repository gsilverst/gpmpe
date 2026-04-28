#!/usr/bin/env python3
"""Local-only PDF parity checker for proprietary migration validation.

This script intentionally reads paths from environment variables or CLI args so
no proprietary locations are hardcoded in tracked repository files.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two PDFs for local parity checks")
    parser.add_argument("generated_pdf", type=Path, help="Path to generated PDF")
    parser.add_argument("reference_pdf", type=Path, help="Path to reference PDF")
    args = parser.parse_args()

    generated = args.generated_pdf.resolve()
    reference = args.reference_pdf.resolve()

    if not generated.exists():
        print(f"ERROR: generated PDF not found: {generated}")
        return 2
    if not reference.exists():
        print(f"ERROR: reference PDF not found: {reference}")
        return 2

    gen_hash = sha256_of(generated)
    ref_hash = sha256_of(reference)

    print(f"generated: {generated}")
    print(f"reference: {reference}")
    print(f"generated_sha256: {gen_hash}")
    print(f"reference_sha256: {ref_hash}")

    if gen_hash == ref_hash:
        print("PARITY: exact-byte-match")
        return 0

    print("PARITY: hash-mismatch")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
