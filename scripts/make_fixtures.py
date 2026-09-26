"""Generate the synthetic ingest fixtures in tests/fixtures/.

    uv run python scripts/make_fixtures.py

Everything here is invented: people, institutions, reference numbers, amounts.
PDFs are written by hand (standard library only) with a real text layer, and no
timestamps, so the output is byte-for-byte reproducible.
"""

from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

IMMIGRATION_LETTER = """\
Northaven Department of Immigration Services
Residence Permits Section, 12 Harbour Road, Port Esk

Our ref: NDIS/RP/2026/004417
Date: 15 September 2026

Alex Example
Flat 3B, 7 Sample Street, Port Esk

Dear Alex Example,

Renewal of Residence Permit

Your residence permit (Dependant category) expires on 30 November 2026.

To remain lawfully resident, your renewal application must be received by
this office no later than 15 November 2026. Applications received after this
date cannot be processed before your permit expires.

You may submit your application from 1 November 2026 onwards.

Please bring your passport, two recent photographs and the sponsor letter.

Yours sincerely,

R. Placeholder
Residence Permits Section
"""

SCHOOL_FEE_EMAIL = """\
From: Bursar <bursar@oakridge-primary.example>
To: Parents of Year 3 <year3-parents@oakridge-primary.example>
Date: Mon, 21 Sep 2026 09:12:00 +0000
Subject: Term 2 tuition fees - payment due 30 October

Dear Parents and Guardians,

Invoices for Term 2 tuition have now been issued through the parent portal.

Term 2 fees of 18,500 are due by 30 October 2026.

Families who pay in full by 16 October 2026 will receive a 2% early-payment
discount, applied automatically.

Payments received after 30 October 2026 incur a 200 administration fee. If you
need a payment plan, please contact the bursary before the due date.

Kind regards,

Jordan Sample
Bursar, Oakridge Primary School
"""

INSURANCE_RENEWAL = """\
Harbourline Mutual Insurance
Home Contents Cover - Renewal Notice

Policy number: HMI-HC-000-5521
Policyholder: Sam Placeholder

Your home contents policy is due for renewal.

To keep your cover without interruption, please renew within 30 days of
receipt of this notice. If we do not hear from you, your cover will end and
any claims after that point will not be paid.

Your renewal premium is 1,240 for the next 12 months. You can renew online,
by phone, or by returning the enclosed form.

Harbourline Mutual Insurance - Customer Renewals Team
"""


def pdf(text: str) -> bytes:
    """A single-page PDF with `text` as a Helvetica text layer, one line per line."""
    lines = text.splitlines()
    ops = ["BT", "/F1 11 Tf", "14 TL", "56 780 Td"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({escaped}) '")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "immigration-letter.pdf").write_bytes(pdf(IMMIGRATION_LETTER))
    (FIXTURES / "school-fee-email.txt").write_text(SCHOOL_FEE_EMAIL, encoding="utf-8")
    (FIXTURES / "insurance-renewal-ambiguous.pdf").write_bytes(pdf(INSURANCE_RENEWAL))
    for p in sorted(FIXTURES.iterdir()):
        print(p.relative_to(FIXTURES.parents[1]))


if __name__ == "__main__":
    main()
