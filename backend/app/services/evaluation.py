from app.db.models import AnalysisRun, ReviewAction
from app.schemas.case import EvaluationSummary


def summarize_analyses(runs: list[AnalysisRun], reviews: list[ReviewAction]) -> EvaluationSummary:
    """Report observable workflow metrics, without claiming unlabeled model quality."""
    latest_reviews: dict[object, ReviewAction] = {}
    for review in sorted(reviews, key=lambda item: (item.created_at, item.id), reverse=True):
        latest_reviews.setdefault(review.analysis_run_id, review)

    completed = [run for run in runs if run.status == "completed"]
    reviewed = [latest_reviews[run.id] for run in completed if run.id in latest_reviews]
    dual_source = sum(
        {citation.get("collection") for citation in (run.citations or [])}
        >= {"historical_complaints", "operating_policies"}
        for run in completed
    )
    latencies = [
        (run.completed_at - run.created_at).total_seconds()
        for run in completed
        if run.completed_at is not None and run.created_at is not None
    ]
    total_cost = sum(float(run.estimated_cost_usd or 0) for run in completed)
    return EvaluationSummary(
        completed_analyses=len(completed),
        reviewed_analyses=len(reviewed),
        approved_reviews=sum(review.action == "approved" for review in reviewed),
        edited_reviews=sum(review.action == "edited" for review in reviewed),
        rejected_reviews=sum(review.action == "rejected" for review in reviewed),
        dual_collection_citation_rate=(dual_source / len(completed) if completed else None),
        average_latency_seconds=(sum(latencies) / len(latencies) if latencies else None),
        total_estimated_cost_usd=total_cost,
        average_estimated_cost_usd=(total_cost / len(completed) if completed else None),
    )
