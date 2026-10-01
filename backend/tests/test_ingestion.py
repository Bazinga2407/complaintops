from datetime import date

from app.services.ingestion import (
    changed_narrative_ids,
    normalize_complaint,
    parse_date,
    parse_yes_no,
)


def test_parse_yes_no() -> None:
    assert parse_yes_no("Yes") is True
    assert parse_yes_no("No") is False
    assert parse_yes_no(None) is None


def test_parse_date_accepts_date_and_timestamp() -> None:
    assert parse_date("2026-08-20") == date(2026, 8, 20)
    assert parse_date("2026-08-20T00:00:42.000Z") == date(2026, 8, 20)
    assert parse_date("08/20/2026") == date(2026, 8, 20)


def test_normalize_complaint_maps_public_fields() -> None:
    source = {
        "complaint_id": "12345",
        "date_received": "2026-08-20",
        "product": "Debt collection",
        "sub_product": "Credit card debt",
        "issue": "Attempts to collect debt not owed",
        "sub_issue": "Debt is not yours",
        "complaint_what_happened": "I believe this is identity theft.",
        "company": "Example Financial",
        "state": "IL",
        "timely": "Yes",
        "consumer_disputed": "No",
    }

    result = normalize_complaint(source)

    assert result["id"] == 12345
    assert result["date_received"] == date(2026, 8, 20)
    assert result["narrative"] == "I believe this is identity theft."
    assert result["timely_response"] is True
    assert result["consumer_disputed"] is False
    assert result["source_payload"] == source


def test_changed_narratives_invalidate_only_stale_embeddings() -> None:
    rows = [
        {"id": 1, "narrative": "same"},
        {"id": 2, "narrative": "updated"},
        {"id": 3, "narrative": "new"},
    ]
    assert changed_narrative_ids(rows, {1: "same", 2: "old"}) == [2]
