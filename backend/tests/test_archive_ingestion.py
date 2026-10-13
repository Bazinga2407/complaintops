import csv
import io
import zipfile
from datetime import date

import pytest

from app.services.archive_ingestion import (
    BALANCED_HISTORY_ARCHIVE_URLS,
    allocate_archive_limits,
    allocate_balanced_quotas,
    iter_archive_narratives,
    normalize_archive_complaint,
    sample_balanced_narratives,
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


def _row(
    complaint_id: str,
    narrative: str,
    *,
    product: str = "Debt collection",
    issue: str = "Attempts to collect debt not owed",
    received: str = "2026-07-15",
) -> dict[str, str]:
    return {
        "Date received": received,
        "Product": product,
        "Sub-product": "Credit card debt",
        "Issue": issue,
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


def test_balanced_quotas_redistribute_capacity_from_small_strata() -> None:
    quotas = allocate_balanced_quotas({"large-a": 10, "large-b": 10, "small": 1}, 9)

    assert sum(quotas.values()) == 9
    assert quotas["small"] == 1
    assert abs(quotas["large-a"] - quotas["large-b"]) <= 1


def test_archive_limits_preserve_the_requested_total() -> None:
    limits = allocate_archive_limits(10_000, len(BALANCED_HISTORY_ARCHIVE_URLS))

    assert sum(limits) == 10_000
    assert max(limits) - min(limits) <= 1


def test_balanced_sample_is_reproducible_and_covers_distinct_strata() -> None:
    archive = _archive_bytes(
        [
            _row(str(index), f"Debt narrative {index}") for index in range(1, 7)
        ]
        + [
            _row(
                str(index),
                f"Mortgage narrative {index}",
                product="Mortgage",
                issue="Trouble during payment process",
                received="2024-05-01",
            )
            for index in range(7, 13)
        ]
    )

    first = sample_balanced_narratives(archive, max_records=6, seed="stable-seed")
    second = sample_balanced_narratives(archive, max_records=6, seed="stable-seed")

    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert len(first) == 6
    assert {row["product"] for row in first} == {"Debt collection", "Mortgage"}
    assert sum(row["product"] == "Debt collection" for row in first) == 3
