"""Shared candidate retrieval for benchmark export and evaluation."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Complaint, ComplaintEmbedding


def retrieve_complaint_candidates(
    db: Session,
    *,
    anchor_id: int,
    product: str,
    anchor_embedding: list[float],
    embedding_model: str,
    limit: int,
) -> list[tuple[Complaint, float]]:
    """Return same-product matches, backfilled globally when the stratum is sparse."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    distance = ComplaintEmbedding.embedding.cosine_distance(anchor_embedding)
    matches = list(
        db.execute(
            select(Complaint, distance.label("distance"))
            .join(ComplaintEmbedding, ComplaintEmbedding.complaint_id == Complaint.id)
            .where(
                Complaint.product == product,
                Complaint.id != anchor_id,
                ComplaintEmbedding.embedding_model == embedding_model,
            )
            .order_by(distance)
            .limit(limit)
        ).all()
    )
    if len(matches) == limit:
        return matches

    selected_ids = [anchor_id, *(complaint.id for complaint, _ in matches)]
    matches.extend(
        db.execute(
            select(Complaint, distance.label("distance"))
            .join(ComplaintEmbedding, ComplaintEmbedding.complaint_id == Complaint.id)
            .where(
                Complaint.id.not_in(selected_ids),
                ComplaintEmbedding.embedding_model == embedding_model,
            )
            .order_by(distance)
            .limit(limit - len(matches))
        ).all()
    )
    return matches
