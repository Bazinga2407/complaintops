from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Complaint, ComplaintEmbedding, PolicyChunk, PolicyDocument
from app.schemas.case import Citation
from app.services.embeddings import (
    EMBEDDING_PRICE_PER_MILLION_TOKENS_USD,
    Embedder,
)


@dataclass(frozen=True)
class RetrievalResult:
    citations: list[Citation]
    input_tokens: int
    estimated_cost_usd: float


def _result(citations: list[Citation], input_tokens: int) -> RetrievalResult:
    return RetrievalResult(
        citations=citations,
        input_tokens=input_tokens,
        estimated_cost_usd=(input_tokens / 1_000_000 * EMBEDDING_PRICE_PER_MILLION_TOKENS_USD),
    )


def search_similar_complaints(
    db: Session,
    embedder: Embedder,
    *,
    query: str,
    product: str | None,
    top_k: int = 5,
    exclude_complaint_id: int | None = None,
) -> RetrievalResult:
    top_k = max(1, min(top_k, 8))
    vectors, input_tokens = embedder.embed([query])
    query_vector = vectors[0]
    distance = ComplaintEmbedding.embedding.cosine_distance(query_vector).label("distance")
    statement = (
        select(Complaint, distance)
        .join(ComplaintEmbedding, ComplaintEmbedding.complaint_id == Complaint.id)
        .where(
            Complaint.narrative.is_not(None),
            ComplaintEmbedding.embedding_model == embedder.model,
        )
        .order_by(distance)
        .limit(top_k)
    )
    if product:
        statement = statement.where(
            or_(Complaint.product == product, Complaint.product.ilike(f"{product}%"))
        )
    if exclude_complaint_id is not None:
        statement = statement.where(Complaint.id != exclude_complaint_id)

    citations = []
    for complaint, raw_distance in db.execute(statement):
        similarity = max(0.0, min(1.0, 1.0 - float(raw_distance)))
        citations.append(
            Citation(
                collection="historical_complaints",
                source_id=str(complaint.id),
                label=(
                    f"CFPB complaint {complaint.id} — {complaint.issue} "
                    f"({similarity:.0%} similarity)"
                ),
                excerpt=(complaint.narrative or "")[:600],
            )
        )
    return _result(citations, input_tokens)


def search_operating_policies(
    db: Session,
    embedder: Embedder,
    *,
    query: str,
    top_k: int = 3,
) -> RetrievalResult:
    top_k = max(1, min(top_k, 6))
    vectors, input_tokens = embedder.embed([query])
    query_vector = vectors[0]
    distance = PolicyChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = db.execute(
        select(PolicyChunk, PolicyDocument, distance)
        .join(PolicyDocument, PolicyDocument.id == PolicyChunk.document_id)
        .where(
            PolicyDocument.is_active.is_(True),
            PolicyChunk.embedding.is_not(None),
            PolicyChunk.embedding_model == embedder.model,
        )
        .order_by(distance)
        .limit(top_k)
    )
    citations = []
    for chunk, document, raw_distance in rows:
        similarity = max(0.0, min(1.0, 1.0 - float(raw_distance)))
        citations.append(
            Citation(
                collection="operating_policies",
                source_id=f"{document.source_path}#{chunk.heading or chunk.chunk_index}",
                label=(
                    f"{document.title} v{document.version} — "
                    f"{chunk.heading or 'Overview'} ({similarity:.0%} similarity)"
                ),
                excerpt=chunk.content[:600],
            )
        )
    return _result(citations, input_tokens)
