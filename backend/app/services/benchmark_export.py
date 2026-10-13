"""Export a diverse, unlabeled retrieval set for human relevance judgment."""

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Complaint, ComplaintEmbedding, PolicyChunk, PolicyDocument
from app.db.session import SessionLocal


@dataclass(frozen=True)
class AnchorCandidate:
    complaint_id: int
    product: str
    issue: str
    narrative: str


def _stable_rank(seed: str, value: str) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def select_diverse_anchors(
    candidates: list[AnchorCandidate],
    *,
    count: int,
    seed: str,
) -> list[AnchorCandidate]:
    """Round-robin product/issue groups after deterministic hash ranking."""
    groups: dict[tuple[str, str], list[AnchorCandidate]] = defaultdict(list)
    for candidate in candidates:
        groups[(candidate.product, candidate.issue)].append(candidate)
    for group in groups.values():
        group.sort(key=lambda item: _stable_rank(seed, str(item.complaint_id)))

    strata = sorted(
        groups,
        key=lambda item: _stable_rank(seed, " | ".join(item)),
    )
    selected: list[AnchorCandidate] = []
    position = 0
    while len(selected) < min(count, len(candidates)):
        added = False
        for stratum in strata:
            group = groups[stratum]
            if position < len(group):
                selected.append(group[position])
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
        position += 1
    return selected


def export_candidates(
    db: Session,
    *,
    anchor_count: int,
    top_k: int,
    seed: str,
) -> list[dict]:
    available = [
        AnchorCandidate(
            complaint_id=complaint_id,
            product=product,
            issue=issue,
            narrative=narrative,
        )
        for complaint_id, product, issue, narrative in db.execute(
            select(Complaint.id, Complaint.product, Complaint.issue, Complaint.narrative)
            .join(ComplaintEmbedding, ComplaintEmbedding.complaint_id == Complaint.id)
            .where(Complaint.narrative.is_not(None))
        )
        if narrative
    ]
    anchors = select_diverse_anchors(available, count=anchor_count, seed=seed)
    judgments: list[dict] = []
    for anchor in anchors:
        anchor_embedding = db.get(ComplaintEmbedding, anchor.complaint_id)
        if anchor_embedding is None:
            continue
        complaint_distance = ComplaintEmbedding.embedding.cosine_distance(
            anchor_embedding.embedding
        )
        matches = db.execute(
            select(Complaint, complaint_distance.label("distance"))
            .join(ComplaintEmbedding, ComplaintEmbedding.complaint_id == Complaint.id)
            .where(
                Complaint.product == anchor.product,
                Complaint.id != anchor.complaint_id,
                ComplaintEmbedding.embedding_model == anchor_embedding.embedding_model,
            )
            .order_by(complaint_distance)
            .limit(top_k)
        )
        policy_distance = PolicyChunk.embedding.cosine_distance(anchor_embedding.embedding)
        policy_headings = list(
            db.scalars(
                select(PolicyChunk.heading)
                .join(PolicyDocument, PolicyDocument.id == PolicyChunk.document_id)
                .where(
                    PolicyDocument.is_active.is_(True),
                    PolicyChunk.embedding.is_not(None),
                    PolicyChunk.embedding_model == anchor_embedding.embedding_model,
                )
                .order_by(policy_distance)
                .limit(5)
            ).all()
        )
        judgments.append(
            {
                "anchor_id": anchor.complaint_id,
                "product": anchor.product,
                "issue": anchor.issue,
                "anchor_excerpt": anchor.narrative[:800],
                "expected_policy_headings": [],
                "retrieved_policy_headings": policy_headings,
                "judged_candidates": [
                    {
                        "complaint_id": complaint.id,
                        "issue": complaint.issue,
                        "excerpt": (complaint.narrative or "")[:800],
                        "relevance_grade": None,
                        "reason": "",
                    }
                    for complaint, _ in matches
                ],
            }
        )
    return judgments


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchors", type=int, default=30)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--seed", default="complaintops-eval-v1")
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "docs" / "retrieval-candidates.json",
    )
    args = parser.parse_args()
    if not 1 <= args.anchors <= 200:
        parser.error("--anchors must be between 1 and 200")
    if args.top_k != 5:
        parser.error("--top-k must be 5 so the output matches the benchmark metrics")

    with SessionLocal() as db:
        judgments = export_candidates(
            db,
            anchor_count=args.anchors,
            top_k=args.top_k,
            seed=args.seed,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(judgments, indent=2) + "\n", encoding="utf-8")
    print(
        f"Exported {len(judgments)} diverse anchors and "
        f"{sum(len(row['judged_candidates']) for row in judgments)} candidate judgments "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
