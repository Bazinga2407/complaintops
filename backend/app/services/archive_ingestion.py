"""Import published complaint narratives from an official CFPB archive ZIP."""

import argparse
import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.ingestion import parse_date, parse_yes_no, upsert_complaints

DEFAULT_ARCHIVE_URL = (
    "https://files.consumerfinance.gov/f/documents/CCDB_Export_20_July_2026.zip"
)
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
REQUIRED_COLUMNS = {
    "Complaint ID",
    "Date received",
    "Product",
    "Issue",
    "Company",
    "Consumer complaint narrative",
}


@dataclass(frozen=True)
class ArchiveIngestionResult:
    processed: int
    archive_url: str


def _optional(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def normalize_archive_complaint(source: dict[str, str]) -> dict[str, Any]:
    """Map one row from the CFPB narrative archive to the stable schema."""
    return {
        "id": int(source["Complaint ID"]),
        "date_received": parse_date(source.get("Date received")),
        "product": _optional(source.get("Product")) or "Unknown",
        "sub_product": _optional(source.get("Sub-product")),
        "issue": _optional(source.get("Issue")) or "Unknown",
        "sub_issue": _optional(source.get("Sub-issue")),
        "narrative": _optional(source.get("Consumer complaint narrative")),
        "company": _optional(source.get("Company")) or "Unknown",
        "company_public_response": _optional(source.get("Company public response")),
        "company_response": _optional(source.get("Company response to consumer")),
        "state": _optional(source.get("State")),
        "zip_code": _optional(source.get("ZIP code")),
        "tags": _optional(source.get("Tags")),
        "consumer_consent_provided": None,
        "submitted_via": _optional(source.get("Submitted via")),
        "date_sent_to_company": parse_date(source.get("Date sent to company")),
        "timely_response": parse_yes_no(source.get("Timely response?")),
        "consumer_disputed": None,
        "source_payload": source,
    }


def download_archive(url: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
    """Download a bounded HTTPS archive into memory."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Archive URL must use HTTPS")

    buffer = io.BytesIO()
    with (
        httpx.Client(timeout=60.0, follow_redirects=True) as client,
        client.stream("GET", url) as response,
    ):
        response.raise_for_status()
        content_length = int(response.headers.get("content-length") or 0)
        if content_length > max_bytes:
            raise ValueError("Archive download exceeds the configured size limit")
        for chunk in response.iter_bytes():
            if buffer.tell() + len(chunk) > max_bytes:
                raise ValueError("Archive download exceeds the configured size limit")
            buffer.write(chunk)
    return buffer.getvalue()


def iter_archive_narratives(
    archive_bytes: bytes,
    *,
    max_records: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield normalized rows that contain a published narrative."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise ValueError("Expected exactly one CSV file in the CFPB archive")
        member = members[0]
        if member.file_size > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Uncompressed archive exceeds the configured size limit")

        with (
            archive.open(member) as raw,
            io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text,
        ):
            reader = csv.DictReader(text)
            columns = set(reader.fieldnames or [])
            missing = sorted(REQUIRED_COLUMNS - columns)
            if missing:
                raise ValueError(f"Archive CSV is missing columns: {', '.join(missing)}")

            yielded = 0
            for source in reader:
                normalized = normalize_archive_complaint(source)
                if not normalized["narrative"]:
                    continue
                yield normalized
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return


def ingest_archive(
    db: Session,
    archive_bytes: bytes,
    *,
    archive_url: str,
    max_records: int = 500,
    batch_size: int = 100,
) -> ArchiveIngestionResult:
    processed = 0
    batch: list[dict[str, Any]] = []
    for row in iter_archive_narratives(archive_bytes, max_records=max_records):
        batch.append(row)
        if len(batch) >= batch_size:
            processed += upsert_complaints(db, batch)
            batch = []
    processed += upsert_complaints(db, batch)
    return ArchiveIngestionResult(processed=processed, archive_url=archive_url)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import published narratives from an official CFPB archive ZIP"
    )
    parser.add_argument("--archive-url", default=DEFAULT_ARCHIVE_URL)
    parser.add_argument("--max-records", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if args.max_records < 1:
        parser.error("--max-records must be positive")
    if not 1 <= args.batch_size <= 1000:
        parser.error("--batch-size must be between 1 and 1000")

    archive_bytes = download_archive(args.archive_url)
    with SessionLocal() as db:
        result = ingest_archive(
            db,
            archive_bytes,
            archive_url=args.archive_url,
            max_records=args.max_records,
            batch_size=args.batch_size,
        )
    print(
        f"Processed {result.processed} archived complaints with published narratives "
        f"from {result.archive_url}"
    )


if __name__ == "__main__":
    main()
