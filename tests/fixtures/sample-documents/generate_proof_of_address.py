"""Generate a text-based PDF utility bill for test fixtures.

Produces a portrait A4 utility bill with fields extractable by Azure AI
Content Understanding. Field labels match the normalization mapping in
document_extraction.py.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fpdf import FPDF

from models import ApplicantProfile, ProofOfAddressSpec, load_profile


def generate_proof_of_address(
    profile: ApplicantProfile, spec: ProofOfAddressSpec, output_path: str
) -> None:
    """Generate a utility bill PDF at output_path."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    page_w = 210

    # --- Header ---
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_xy(10, 15)
    pdf.cell(page_w - 20, 10, spec.provider_name, align="C")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(10, 27)
    pdf.cell(page_w - 20, 6, "123 Power Lane, Springfield, IL 62701", align="C")
    pdf.set_xy(10, 33)
    pdf.cell(page_w - 20, 6, "Phone: (217) 555-0100  |  www.springfieldelectric.example.com", align="C")

    # Separator
    pdf.set_draw_color(0, 0, 0)
    pdf.line(10, 42, page_w - 10, 42)

    # --- Account Information ---
    y = 50
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(15, y)
    pdf.cell(0, 8, "Account Information")
    y += 12

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(15, y)
    pdf.cell(45, 7, "Account Number:")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(62, y)
    pdf.cell(0, 7, spec.account_number)
    y += 10

    # --- Service Address ---
    y += 5
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(15, y)
    pdf.cell(0, 8, "Service Address")
    y += 12

    address_fields = [
        ("Name", profile.full_name),
        ("Address", profile.full_address),
    ]

    for label, value in address_fields:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_xy(15, y)
        pdf.cell(45, 7, f"{label}:")

        pdf.set_font("Helvetica", "", 11)
        pdf.set_xy(62, y)
        pdf.cell(0, 7, value)
        y += 10

    # --- Billing Summary ---
    y += 5
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(15, y)
    pdf.cell(0, 8, "Billing Summary")
    y += 12

    bill_date = datetime.strptime(spec.bill_date, "%Y-%m-%d").strftime("%m/%d/%Y")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(15, y)
    pdf.cell(45, 7, "Bill Date:")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(62, y)
    pdf.cell(0, 7, bill_date)
    y += 10

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(15, y)
    pdf.cell(45, 7, "Amount Due:")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_xy(62, y)
    pdf.cell(0, 7, f"${spec.amount_due:.2f}")
    y += 15

    # --- Billing Breakdown Table ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(15, y)
    pdf.cell(0, 8, "Billing Breakdown")
    y += 12

    col_widths = (100, 50)
    rows = [
        ("Description", "Amount"),
        ("Electric Service - Residential", f"${spec.amount_due - 22.50 - 8.93:.2f}"),
        ("Distribution Charge", "$22.50"),
        ("Taxes & Fees", "$8.93"),
        ("Total Due", f"${spec.amount_due:.2f}"),
    ]

    pdf.set_xy(15, y)
    with pdf.table(
        col_widths=col_widths,
        text_align="LEFT",
        first_row_as_headings=True,
        line_height=7,
    ) as table:
        for i, row_data in enumerate(rows):
            row = table.row()
            for j, cell_text in enumerate(row_data):
                if i == 0 or i == len(rows) - 1:
                    pdf.set_font("Helvetica", "B", 10)
                else:
                    pdf.set_font("Helvetica", "", 10)
                row.cell(cell_text)

    # --- Footer ---
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_xy(10, 270)
    pdf.cell(
        page_w - 20,
        5,
        "This is a sample utility bill generated for testing purposes only.",
        align="C",
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)


if __name__ == "__main__":
    import sys

    profile_path = sys.argv[1] if len(sys.argv) > 1 else "applicants/john-smith.json"
    profile, _, proof_spec = load_profile(profile_path)

    out_dir = f"{profile.first_name.lower()}-{profile.last_name.lower()}"
    out_path = f"{out_dir}/proof_of_address.pdf"

    generate_proof_of_address(profile, proof_spec, out_path)
    print(f"Generated: {out_path}")
