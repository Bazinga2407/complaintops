import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Complaint, ComplaintEmbedding
from app.db.session import SessionLocal
from app.services.cfpb_client import CfpbClient


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    normalized = value.strip()
    try:
        return date.fromisoformat(normalized[:10])
    except ValueError:
        month, day, year = (int(part) for part in normalized.split("/"))
        return date(year, month, day)


def parse_yes_no(value: str | bool | None) -> bool | None:
    if isinstance(value, bool):
        return value
    if value == "Yes":
        return True
    if value == "No":
        return False
    return None


def normalize_complaint(source: dict[str, Any]) -> dict[str, Any]:
    """Map one CFPB API record to the stable ComplaintOps schema."""
    return {
        "id": int(source["complaint_id"]),
        "date_received": parse_date(source.get("date_received")),
        "product": source.get("product") or "Unknown",
        "sub_product": source.get("sub_product"),
        "issue": source.get("issue") or "Unknown",
        "sub_issue": source.get("sub_issue"),
        "narrative": source.get("complaint_what_happened") or None,
        "company": source.get("company") or "Unknown",
        "company_public_response": source.get("company_public_response") or None,
        "company_response": source.get("company_response") or None,
        "state": source.get("state") or None,
        "zip_code": source.get("zip_code") or None,
        "tags": source.get("tags") or None,
        "consumer_consent_provided": source.get("consumer_consent_provided") or None,
        "submitted_via": source.get("submitted_via") or None,
        "date_sent_to_company": parse_date(source.get("date_sent_to_company")),
        "timely_response": parse_yes_no(source.get("timely")),
        "consumer_disputed": parse_yes_no(source.get("consumer_disputed")),
        "source_payload": source,
    }


@dataclass(frozen=True)
class IngestionResult:
    processed: int
    date_from: date
    date_to: date


def upsert_complaints(db: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    unique_rows = list({row["id"]: row for row in rows}.values())
    existing_narratives = dict(
        db.execute(
            select(Complaint.id, Complaint.narrative).where(
                Complaint.id.in_([row["id"] for row in unique_rows])
            )
        ).all()
    )
    changed_ids = changed_narrative_ids(unique_rows, existing_narratives)
    statement = insert(Complaint).values(unique_rows)
    update_columns = {
        column.name: getattr(statement.excluded, column.name)
        for column in Complaint.__table__.columns
        if column.name not in {"id", "ingested_at"}
    }
    db.execute(statement.on_conflict_do_update(index_elements=[Complaint.id], set_=update_columns))
    if changed_ids:
        db.execute(
            delete(ComplaintEmbedding).where(ComplaintEmbedding.complaint_id.in_(changed_ids))
        )
    db.commit()
    return len(unique_rows)


def changed_narrative_ids(rows: list[dict[str, Any]], existing: dict[int, str | None]) -> list[int]:
    """Invalidate vectors only when a previously embedded narrative changed."""
    return [
        row["id"]
        for row in rows
        if row["id"] in existing and row["narrative"] != existing[row["id"]]
    ]


def ingest_window(
    db: Session,
    client: CfpbClient,
    *,
    date_from: date,
    date_to: date,
    page_size: int = 100,
    max_records: int | None = None,
    products: list[str] | None = None,
    states: list[str] | None = None,
    narratives_only: bool = False,
) -> IngestionResult:
    processed = 0
    batch: list[dict[str, Any]] = []
    for source in client.iter_complaints(
        date_from=date_from,
        date_to=date_to,
        page_size=page_size,
        max_records=max_records,
        products=products,
        states=states,
        narratives_only=narratives_only,
    ):
        batch.append(normalize_complaint(source))
        if len(batch) >= page_size:
            processed += upsert_complaints(db, batch)
            batch = []
    processed += upsert_complaints(db, batch)
    return IngestionResult(processed=processed, date_from=date_from, date_to=date_to)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import public CFPB consumer complaints")
    parser.add_argument("--days", type=int, default=7, help="Inclusive lookback window")
    parser.add_argument(
        "--date-from",
        type=date.fromisoformat,
        help="Start date in YYYY-MM-DD format; overrides --days",
    )
    parser.add_argument(
        "--date-to",
        type=date.fromisoformat,
        help="Exclusive end date in YYYY-MM-DD format; overrides --days",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-records", type=int)
    parser.add_argument(
        "--product",
        action="append",
        dest="products",
        help="Exact CFPB product label; repeat this option for multiple products",
    )
    parser.add_argument(
        "--state",
        action="append",
        dest="states",
        help="Two-letter state code; repeat this option for multiple states",
    )
    parser.add_argument(
        "--narratives-only",
        action="store_true",
        help="Import only complaints with a published consumer narrative",
    )
    args = parser.parse_args()

    if bool(args.date_from) != bool(args.date_to):
        parser.error("--date-from and --date-to must be provided together")
    date_to = args.date_to or datetime.now(UTC).date()
    date_from = args.date_from or date_to - timedelta(days=max(args.days - 1, 0))
    client = CfpbClient(get_settings().cfpb_api_base_url)
    with SessionLocal() as db:
        result = ingest_window(
            db,
            client,
            date_from=date_from,
            date_to=date_to,
            page_size=args.page_size,
            max_records=args.max_records,
            products=args.products,
            states=args.states,
            narratives_only=args.narratives_only,
        )
    print(
        f"Processed {result.processed} complaints "
        f"from {result.date_from.isoformat()} through {result.date_to.isoformat()}"
    )


if __name__ == "__main__":
    main()
