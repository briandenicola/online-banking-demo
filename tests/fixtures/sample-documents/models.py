"""Data models for sample document generation.

Defines typed dataclasses for applicant profiles and document specs,
loaded from JSON profile files under applicants/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SSN4_RE = re.compile(r"^\d{4}$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")
_ZIP_RE = re.compile(r"^\d{5}$")
_VALID_ACCOUNT_TYPES = {"checking", "savings", "both"}


@dataclass
class ApplicantProfile:
    first_name: str
    last_name: str
    date_of_birth: str
    street: str
    city: str
    state: str
    zip_code: str
    country: str
    email: str
    phone: str | None
    ssn_last4: str
    employer: str
    job_title: str
    annual_income: float
    account_type: str

    def __post_init__(self) -> None:
        if not _ISO_DATE_RE.match(self.date_of_birth):
            raise ValueError(f"date_of_birth must be ISO format (YYYY-MM-DD), got: {self.date_of_birth}")

        dob = date.fromisoformat(self.date_of_birth)
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 18:
            raise ValueError(f"Applicant must be 18+, got age {age}")

        if not _SSN4_RE.match(self.ssn_last4):
            raise ValueError(f"ssn_last4 must be exactly 4 digits, got: {self.ssn_last4}")

        if not _STATE_RE.match(self.state):
            raise ValueError(f"state must be 2-letter US state code, got: {self.state}")

        if not _ZIP_RE.match(self.zip_code):
            raise ValueError(f"zip_code must be 5-digit US ZIP, got: {self.zip_code}")

        if self.account_type not in _VALID_ACCOUNT_TYPES:
            raise ValueError(f"account_type must be one of {_VALID_ACCOUNT_TYPES}, got: {self.account_type}")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def full_address(self) -> str:
        return f"{self.street}, {self.city}, {self.state} {self.zip_code}"

    def format_dob(self, fmt: str = "%m/%d/%Y") -> str:
        return datetime.strptime(self.date_of_birth, "%Y-%m-%d").strftime(fmt)


@dataclass
class PhotoIdSpec:
    document_number: str
    expiry_date: str
    issuing_state: str
    document_class: str

    def __post_init__(self) -> None:
        if not _ISO_DATE_RE.match(self.expiry_date):
            raise ValueError(f"expiry_date must be ISO format, got: {self.expiry_date}")

    def format_expiry(self, fmt: str = "%m/%d/%Y") -> str:
        return datetime.strptime(self.expiry_date, "%Y-%m-%d").strftime(fmt)


@dataclass
class ProofOfAddressSpec:
    provider_name: str
    account_number: str
    bill_date: str
    amount_due: float

    def __post_init__(self) -> None:
        if not _ISO_DATE_RE.match(self.bill_date):
            raise ValueError(f"bill_date must be ISO format, got: {self.bill_date}")


def load_profile(path: str) -> tuple[ApplicantProfile, PhotoIdSpec, ProofOfAddressSpec]:
    """Load an applicant profile from a JSON file.

    Returns a tuple of (ApplicantProfile, PhotoIdSpec, ProofOfAddressSpec).
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    ap = data["applicantProfile"]
    addr = ap["address"]
    profile = ApplicantProfile(
        first_name=ap["firstName"],
        last_name=ap["lastName"],
        date_of_birth=ap["dateOfBirth"],
        street=addr["street"],
        city=addr["city"],
        state=addr["state"],
        zip_code=addr["zip"],
        country=addr["country"],
        email=ap["email"],
        phone=ap.get("phone"),
        ssn_last4=ap["ssn_last4"],
        employer=ap["employer"],
        job_title=ap["jobTitle"],
        annual_income=ap["annualIncome"],
        account_type=ap["accountType"],
    )

    pid = data["photoIdSpec"]
    photo_id_spec = PhotoIdSpec(
        document_number=pid["documentNumber"],
        expiry_date=pid["expiryDate"],
        issuing_state=pid["issuingState"],
        document_class=pid["documentClass"],
    )

    poa = data["proofOfAddressSpec"]
    proof_spec = ProofOfAddressSpec(
        provider_name=poa["providerName"],
        account_number=poa["accountNumber"],
        bill_date=poa["billDate"],
        amount_due=poa["amountDue"],
    )

    return profile, photo_id_spec, proof_spec
