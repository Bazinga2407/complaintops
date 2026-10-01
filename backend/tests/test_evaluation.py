from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.models import AnalysisRun, ReviewAction
from app.services.evaluation import summarize_analyses


def test_evaluation_summary_uses_latest_review_and_both_citation_sources() -> None:
    now = datetime.now(UTC)
    run_id = uuid4()
    run = AnalysisRun(
        id=run_id,
        case_id=uuid4(),
        status="completed",
        provider="mock",
        citations=[
            {"collection": "historical_complaints"},
            {"collection": "operating_policies"},
        ],
        estimated_cost_usd=0.02,
        created_at=now,
        completed_at=now + timedelta(seconds=4),
    )
    earlier = ReviewAction(
        id=1,
        analysis_run_id=run_id,
        action="rejected",
        reviewer="Operator",
        created_at=now + timedelta(seconds=5),
    )
    latest = ReviewAction(
        id=2,
        analysis_run_id=run_id,
        action="approved",
        reviewer="Operator",
        created_at=now + timedelta(seconds=6),
    )

    result = summarize_analyses([run], [earlier, latest])

    assert result.completed_analyses == 1
    assert result.reviewed_analyses == 1
    assert result.approved_reviews == 1
    assert result.rejected_reviews == 0
    assert result.dual_collection_citation_rate == 1.0
    assert result.average_latency_seconds == 4.0
    assert result.total_estimated_cost_usd == 0.02
