import csv
import io
import zipfile
from datetime import date

import pytest

from app.services.archive_ingestion import (
    iter_archive_narratives,
    normalize_archive_complaint,
)

FIELDNAMES = [
    "Date received",
    "Product",
    "Sub-product",
    "Issue",
    "Sub-issue",
    "Consumer complaint narrative",
    "Company public response",
    "Company",
    "State",
    "ZIP code",
    "Tags",
    "Submitted via",
    "Date sent to company",
    "Company response to consumer",
    "Timely response?",
    "Complaint ID",
]


def _archive_bytes(rows: list[dict[str, str]], fieldnames: list[str] = FIELDNAMES) -> bytes:
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("complaints.csv", csv_buffer.getvalue())
    return archive_buffer.getvalue()


def _row(complaint_id: str, narrative: str) -> dict[str, str]:
    return {
        "Date received": "2026-07-15",
        "Product": "Debt collection",
        "Sub-product": "Credit card debt",
        "Issue": "Attempts to collect debt not owed",
        "Sub-issue": "Debt is not yours",
        "Consumer complaint narrative": narrative,
        "Company public response": "",
        "Company": "Example Financial",
        "State": "IL",
        "ZIP code": "606XX",
        "Tags": "",
        "Submitted via": "Web",
        "Date sent to company": "2026-07-16",
        "Company response to consumer": "Closed with explanation",
        "Timely response?": "Yes",
        "Complaint ID": complaint_id,
    }


def test_normalize_archive_complaint_maps_csv_fields() -> None:
    result = normalize_archive_complaint(_row("12345", "A published narrative."))

    assert result["id"] == 12345
    assert result["date_received"] == date(2026, 7, 15)
    assert result["narrative"] == "A published narrative."
    assert result["company_response"] == "Closed with explanation"
    assert result["timely_response"] is True
    assert result["consumer_disputed"] is None


def test_archive_iterator_filters_empty_narratives_and_honors_limit() -> None:
    archive = _archive_bytes(
        [
            _row("1", ""),
            _row("2", "First narrative"),
            _row("3", "Second narrative"),
        ]
    )

    rows = list(iter_archive_narratives(archive, max_records=1))

    assert [row["id"] for row in rows] == [2]


def test_archive_iterator_rejects_missing_required_columns() -> None:
    archive = _archive_bytes([], fieldnames=["Complaint ID"])

    with pytest.raises(ValueError, match="missing columns"):
        list(iter_archive_narratives(archive))
