"""Import published complaint narratives from an official CFPB archive ZIP."""

import argparse
import csv
import hashlib
import heapq
import io
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.ingestion import parse_date, parse_yes_no, upsert_complaints

CFPB_ARCHIVE_BASE_URL = "https://files.consumerfinance.gov/f/documents/"
DEFAULT_ARCHIVE_URL = f"{CFPB_ARCHIVE_BASE_URL}CCDB_Export_20_July_2026.zip"
BALANCED_HISTORY_ARCHIVE_URLS = (
    f"{CFPB_ARCHIVE_BASE_URL}CCDB_Export_1_December_2011_through_April_2018.zip",
    f"{CFPB_ARCHIVE_BASE_URL}CCDB_Export_2_May_2018_through_April_2021.zip",
    f"{CFPB_ARCHIVE_BASE_URL}CCDB_Export_3_May_2021_through_October_2022.zip",
    f"{CFPB_ARCHIVE_BASE_URL}CCDB_Export_5_September_2023_through_March_2024.zip",
    f"{CFPB_ARCHIVE_BASE_URL}CCDB_Export_9_January_2025_through_February_2025.zip",
    DEFAULT_ARCHIVE_URL,
)
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
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
    sampling: str
    strata: int


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


def _narrative_length_bucket(narrative: str) -> str:
    length = len(narrative)
    if length < 500:
        return "short"
    if length < 1_500:
        return "medium"
    return "long"


def archive_stratum(row: dict[str, Any]) -> str:
    """Group records for broad product, issue, year, and narrative-length coverage."""
    received = row["date_received"]
    return " | ".join(
        (
            row["product"],
            row["issue"],
            str(received.year),
            _narrative_length_bucket(row["narrative"]),
        )
    )


def allocate_balanced_quotas(counts: dict[str, int], max_records: int) -> dict[str, int]:
    """Water-fill available strata so common categories cannot dominate the sample."""
    target = min(max_records, sum(counts.values()))
    quotas = {key: 0 for key in counts}
    active = sorted(key for key, count in counts.items() if count > 0)
    remaining = target

    while remaining and active:
        per_stratum, extra = divmod(remaining, len(active))
        if per_stratum == 0:
            for key in active[:extra]:
                quotas[key] += 1
            break

        consumed = 0
        next_active: list[str] = []
        for index, key in enumerate(active):
            requested = per_stratum + (1 if index < extra else 0)
            available = counts[key] - quotas[key]
            granted = min(requested, available)
            quotas[key] += granted
            consumed += granted
            if quotas[key] < counts[key]:
                next_active.append(key)
        if consumed == 0:
            break
        remaining -= consumed
        active = next_active

    return quotas


def allocate_archive_limits(max_records: int, archive_count: int) -> list[int]:
    """Split a total corpus target evenly across selected historical periods."""
    if archive_count < 1:
        raise ValueError("archive_count must be positive")
    base, extra = divmod(max_records, archive_count)
    return [base + (1 if index < extra else 0) for index in range(archive_count)]


def _selection_rank(seed: str, complaint_id: int) -> int:
    digest = hashlib.sha256(f"{seed}:{complaint_id}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def sample_balanced_narratives(
    archive_bytes: bytes,
    *,
    max_records: int,
    seed: str = "complaintops-v1",
) -> list[dict[str, Any]]:
    """Select a reproducible, memory-bounded sample across operationally useful strata."""
    counts = Counter(archive_stratum(row) for row in iter_archive_narratives(archive_bytes))
    quotas = allocate_balanced_quotas(dict(counts), max_records)
    selected: dict[str, list[tuple[int, int, dict[str, Any]]]] = {
        key: [] for key, quota in quotas.items() if quota
    }

    for row in iter_archive_narratives(archive_bytes):
        stratum = archive_stratum(row)
        quota = quotas.get(stratum, 0)
        if quota == 0:
            continue
        rank = _selection_rank(seed, row["id"])
        # A min-heap of negative ranks exposes the least desirable (largest) rank.
        entry = (-rank, -row["id"], row)
        bucket = selected[stratum]
        if len(bucket) < quota:
            heapq.heappush(bucket, entry)
        elif entry > bucket[0]:
            heapq.heapreplace(bucket, entry)

    ranked_rows = [
        (stratum, -negative_rank, -negative_id, row)
        for stratum, bucket in selected.items()
        for negative_rank, negative_id, row in bucket
    ]
    ranked_rows.sort(key=lambda item: (item[0], item[1], item[2]))
    return [row for _, _, _, row in ranked_rows]


def ingest_archive(
    db: Session,
    archive_bytes: bytes,
    *,
    archive_url: str,
    max_records: int = 10_000,
    batch_size: int = 100,
    sampling: str = "balanced",
    seed: str = "complaintops-v1",
) -> ArchiveIngestionResult:
    processed = 0
    batch: list[dict[str, Any]] = []
    if sampling == "balanced":
        rows: Iterator[dict[str, Any]] = iter(
            sample_balanced_narratives(
                archive_bytes,
                max_records=max_records,
                seed=seed,
            )
        )
    elif sampling == "sequential":
        rows = iter_archive_narratives(archive_bytes, max_records=max_records)
    else:
        raise ValueError("sampling must be 'balanced' or 'sequential'")

    strata: set[str] = set()
    for row in rows:
        strata.add(archive_stratum(row))
        batch.append(row)
        if len(batch) >= batch_size:
            processed += upsert_complaints(db, batch)
            batch = []
    processed += upsert_complaints(db, batch)
    return ArchiveIngestionResult(
        processed=processed,
        archive_url=archive_url,
        sampling=sampling,
        strata=len(strata),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import published narratives from an official CFPB archive ZIP"
    )
    parser.add_argument(
        "--archive-url",
        help="One official archive URL; overrides the selected archive set",
    )
    parser.add_argument(
        "--archive-set",
        choices=("recent", "balanced-history"),
        default="recent",
        help="Use one recent archive or curated periods spanning 2011–2026",
    )
    parser.add_argument("--max-records", type=int, default=10_000)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--sampling",
        choices=("balanced", "sequential"),
        default="balanced",
        help="Balanced samples product/issue/year/length strata; sequential preserves file order",
    )
    parser.add_argument("--seed", default="complaintops-v1")
    args = parser.parse_args()
    if args.max_records < 1:
        parser.error("--max-records must be positive")
    if not 1 <= args.batch_size <= 1000:
        parser.error("--batch-size must be between 1 and 1000")

    if args.archive_url:
        archive_urls = (args.archive_url,)
    elif args.archive_set == "balanced-history":
        archive_urls = BALANCED_HISTORY_ARCHIVE_URLS
    else:
        archive_urls = (DEFAULT_ARCHIVE_URL,)
    limits = allocate_archive_limits(args.max_records, len(archive_urls))

    processed = 0
    with SessionLocal() as db:
        for archive_url, limit in zip(archive_urls, limits, strict=True):
            archive_bytes = download_archive(archive_url)
            result = ingest_archive(
                db,
                archive_bytes,
                archive_url=archive_url,
                max_records=limit,
                batch_size=args.batch_size,
                sampling=args.sampling,
                seed=args.seed,
            )
            processed += result.processed
            print(
                f"Processed {result.processed} archived complaints from {archive_url} "
                f"across {result.strata} strata"
            )
    print(
        f"Archive ingestion complete: {processed} complaints from {len(archive_urls)} "
        f"archive periods using {args.sampling} sampling"
    )


if __name__ == "__main__":
    main()
