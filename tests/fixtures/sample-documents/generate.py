"""Unified CLI script for generating sample documents.

Generates all test fixture PDFs (photo ID, proof of address) for a given
applicant profile. Outputs files to a directory named after the applicant.

Usage:
    python generate.py
    python generate.py --profile applicants/john-smith.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from generate_photo_id import generate_photo_id
from generate_proof_of_address import generate_proof_of_address
from models import load_profile


def main(profile_path: str) -> None:
    """Load profile and generate all sample documents."""
    profile, photo_spec, proof_spec = load_profile(profile_path)

    out_dir = f"{profile.first_name.lower()}-{profile.last_name.lower()}"
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    documents: list[tuple[str, str]] = []

    photo_id_path = f"{out_dir}/photo_id.pdf"
    generate_photo_id(profile, photo_spec, photo_id_path)
    documents.append(("Photo ID", photo_id_path))

    proof_path = f"{out_dir}/proof_of_address.pdf"
    generate_proof_of_address(profile, proof_spec, proof_path)
    documents.append(("Proof of Address", proof_path))

    print(f"\nGenerated documents for: {profile.full_name}")
    print(f"Output directory: {out_dir}/")
    print("-" * 40)
    for doc_type, path in documents:
        size = Path(path).stat().st_size
        print(f"  {doc_type}: {path} ({size:,} bytes)")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate sample documents for account opening test fixtures."
    )
    parser.add_argument(
        "--profile",
        default="applicants/john-smith.json",
        help="Path to applicant profile JSON (default: applicants/john-smith.json)",
    )
    args = parser.parse_args()
    main(args.profile)
