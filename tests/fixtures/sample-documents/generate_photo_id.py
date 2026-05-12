"""Generate a text-based PDF driver's license for test fixtures.

Produces a landscape card with fields extractable by Azure AI Content
Understanding. Field labels match the normalization mapping in
document_extraction.py.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from models import ApplicantProfile, PhotoIdSpec, load_profile

# Card dimensions (landscape A5-ish)
CARD_W = 210
CARD_H = 130


def generate_photo_id(profile: ApplicantProfile, spec: PhotoIdSpec, output_path: str) -> None:
    """Generate a driver's license PDF at output_path."""
    pdf = FPDF(orientation="L", unit="mm", format=(CARD_H, CARD_W))
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_xy(10, 10)
    pdf.cell(CARD_W - 20, 10, "STATE OF ILLINOIS - DRIVER LICENSE", align="C")

    # Separator line
    pdf.set_draw_color(0, 0, 0)
    pdf.line(10, 24, CARD_W - 10, 24)

    # Field layout
    fields = [
        ("Name", profile.full_name),
        ("Date of Birth", profile.format_dob()),
        ("Address", profile.full_address),
        ("License Number", spec.document_number),
        ("Expiry Date", spec.format_expiry()),
        ("Issuing State", spec.issuing_state),
        ("Class", spec.document_class),
    ]

    y = 32
    for label, value in fields:
        # Label
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(15, y)
        pdf.cell(45, 7, f"{label}:")

        # Value
        pdf.set_font("Helvetica", "", 11)
        pdf.set_xy(62, y)
        pdf.cell(130, 7, value)

        y += 12

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)


if __name__ == "__main__":
    import sys

    profile_path = sys.argv[1] if len(sys.argv) > 1 else "applicants/john-smith.json"
    profile, photo_spec, _ = load_profile(profile_path)

    out_dir = f"{profile.first_name.lower()}-{profile.last_name.lower()}"
    out_path = f"{out_dir}/photo_id.pdf"

    generate_photo_id(profile, photo_spec, out_path)
    print(f"Generated: {out_path}")
