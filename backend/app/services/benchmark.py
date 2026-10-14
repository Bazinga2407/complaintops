"""Small, transparent quality checks. Live model calls are opt-in only."""

import argparse
import json
import math
import re
import uuid
from importlib.resources import files
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.openai_agent import analyze_with_openai
from app.core.config import get_settings
from app.db.models import Case, Complaint, ComplaintEmbedding, PolicyChunk, PolicyDocument
from app.db.session import SessionLocal
from app.services.retrieval_candidates import retrieve_complaint_candidates


def load_judgments(source: Path | None = None) -> list[dict]:
    if source is None:
        packaged = files("app.evaluations").joinpath("retrieval_judgments.json")
        payload = json.loads(packaged.read_text(encoding="utf-8"))
    else:
        payload = json.loads(source.read_text(encoding="utf-8"))
    return parse_judgments(payload)


def parse_judgments(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("judgments")
    if not isinstance(payload, list):
        raise TypeError("Judgment file must contain a list or a judgments list")
    return payload


def load_live_cases() -> list[dict]:
    source = files("app.evaluations").joinpath("golden_cases.json")
    return json.loads(source.read_text(encoding="utf-8"))


def _relevance_grade(candidate: dict) -> int | None:
    grade = candidate.get("relevance_grade")
    if grade is None and candidate.get("relevant") is not None:
        grade = 3 if candidate["relevant"] else 0
    if grade is None:
        return None
    if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
        raise ValueError("relevance_grade must be an integer from 0 through 3")
    return grade


def normalized_dcg_at_k(candidates: list[dict], k: int = 5) -> float | None:
    """Score graded relevance and ranking quality from zero to one."""
    grades = [_relevance_grade(candidate) for candidate in candidates[:k]]
    if len(grades) != k or any(grade is None for grade in grades):
        return None
    numeric_grades = [int(grade) for grade in grades if grade is not None]

    def dcg(values: list[int]) -> float:
        return sum((2**grade - 1) / math.log2(rank + 2) for rank, grade in enumerate(values))

    ideal = dcg(sorted(numeric_grades, reverse=True))
    if ideal == 0:
        return 0.0
    return dcg(numeric_grades) / ideal


def score_retrieval(rows: list[dict]) -> dict:
    count = len(rows)
    known_pair_rows = [
        row
        for row in rows
        if row.get("known_relevant_evaluated", "known_relevant_rank" in row)
    ]
    hits = [row["known_relevant_rank"] for row in known_pair_rows if row["known_relevant_rank"]]
    judged_slots = [
        candidate
        for row in rows
        for candidate in row.get("retrieved_top_5", [])
        if _relevance_grade(candidate) is not None
    ]
    expected_judgment_count = count * 5
    judgment_coverage = (
        len(judged_slots) / expected_judgment_count if expected_judgment_count else None
    )
    judged_precision = (
        sum((_relevance_grade(candidate) or 0) > 0 for candidate in judged_slots)
        / expected_judgment_count
        if expected_judgment_count and len(judged_slots) == expected_judgment_count
        else None
    )
    ndcg_scores = [
        normalized_dcg_at_k(row.get("retrieved_top_5", []), 5) for row in rows
    ]
    graded_coverage = (
        sum(score is not None for score in ndcg_scores) / count if count else None
    )
    graded_ndcg = (
        sum(score for score in ndcg_scores if score is not None) / count
        if count and all(score is not None for score in ndcg_scores)
        else None
    )
    policy_rows = [row for row in rows if row.get("policy_ranking_evaluated", True)]
    policy_ranks = [row.get("expected_policy_rank") for row in policy_rows]
    policy_ranking_evaluated = bool(policy_rows) and len(policy_rows) == count
    return {
        "sample_size": count,
        "judged_precision_at_5": judged_precision,
        "judgment_coverage_at_5": judgment_coverage,
        "graded_ndcg_at_5": graded_ndcg,
        "graded_judgment_coverage_at_5": graded_coverage,
        "known_relevant_hit_at_10": (
            len(hits) / len(known_pair_rows) if known_pair_rows else None
        ),
        "known_relevant_mrr_at_10": (
            sum(1 / rank for rank in hits) / len(known_pair_rows)
            if known_pair_rows
            else None
        ),
        "policy_top_1_accuracy": (
            sum(row["policy_top_1_correct"] for row in policy_rows) / count
            if policy_ranking_evaluated
            else None
        ),
        "policy_hit_at_3": (
            sum(rank is not None and rank <= 3 for rank in policy_ranks) / count
            if count and policy_ranking_evaluated
            else None
        ),
        "policy_mrr_at_3": (
            sum(1 / rank if rank is not None and rank <= 3 else 0 for rank in policy_ranks) / count
            if count and policy_ranking_evaluated
            else None
        ),
        "limitations": (
            f"{count} anchors and {len(judged_slots)} judged top-five candidates from "
            "this CFPB snapshot. The sample is small and not representative of every product or "
            "complaint type. The anchor uses an existing complaint embedding, not a fresh "
            "agent-generated query. The known-pair score is retained only as a regression signal; "
            "its relevance labels are incomplete because one preselected complaint is not a "
            "complete relevance set."
        ),
        "examples": rows,
    }


def evaluate_retrieval(db: Session, judgments: list[dict] | None = None) -> dict:
    rows = []
    for judgment in (judgments if judgments is not None else load_judgments()):
        anchor = db.get(ComplaintEmbedding, judgment["anchor_id"])
        complaint = db.get(Complaint, judgment["anchor_id"])
        known_relevant_id = judgment.get("known_relevant_id")
        relevant = (
            db.get(ComplaintEmbedding, known_relevant_id) if known_relevant_id is not None else None
        )
        if anchor is None or complaint is None or (
            known_relevant_id is not None and relevant is None
        ):
            raise RuntimeError("A judged CFPB complaint is missing an embedding")
        retrieved_top_5_ids = [
            candidate.id
            for candidate, _ in retrieve_complaint_candidates(
                db,
                anchor_id=complaint.id,
                product=complaint.product,
                anchor_embedding=anchor.embedding,
                embedding_model=anchor.embedding_model,
                limit=5,
            )
        ]
        known_relevant_rank = None
        if known_relevant_id is not None:
            regression_ids = [
                candidate.id
                for candidate, _ in retrieve_complaint_candidates(
                    db,
                    anchor_id=complaint.id,
                    product=complaint.product,
                    anchor_embedding=anchor.embedding,
                    embedding_model=anchor.embedding_model,
                    limit=10,
                )
            ]
            if known_relevant_id in regression_ids:
                known_relevant_rank = regression_ids.index(known_relevant_id) + 1
        judged_by_id = {
            item["complaint_id"]: item for item in judgment.get("judged_candidates", [])
        }
        retrieved_top_5 = [
            {
                "complaint_id": complaint_id,
                "relevant": judged_by_id.get(complaint_id, {}).get("relevant"),
                "relevance_grade": judged_by_id.get(complaint_id, {}).get("relevance_grade"),
                "judgment_reason": judged_by_id.get(complaint_id, {}).get("reason"),
            }
            for complaint_id in retrieved_top_5_ids
        ]
        policy_distance = PolicyChunk.embedding.cosine_distance(anchor.embedding)
        policy_headings = list(
            db.scalars(
                select(PolicyChunk.heading)
                .join(PolicyDocument, PolicyDocument.id == PolicyChunk.document_id)
                .where(
                    PolicyDocument.is_active.is_(True),
                    PolicyChunk.embedding_model == anchor.embedding_model,
                )
                .order_by(policy_distance)
                .limit(3)
            ).all()
        )
        expected_policy_headings = judgment.get("expected_policy_headings") or (
            [judgment["expected_policy_heading"]]
            if judgment.get("expected_policy_heading")
            else []
        )
        expected_policy_ranks = [
            policy_headings.index(heading) + 1
            for heading in expected_policy_headings
            if heading in policy_headings
        ]
        row = {
            "anchor_id": complaint.id,
            "known_relevant_rank": known_relevant_rank,
            "known_relevant_evaluated": known_relevant_id is not None,
            "retrieved_top_5": retrieved_top_5,
            "policy_ranking_evaluated": bool(expected_policy_headings),
        }
        if known_relevant_id is not None:
            row["known_relevant_id"] = known_relevant_id
        if expected_policy_headings:
            row.update(
                {
                    "expected_policy_headings": expected_policy_headings,
                    "top_policy_heading": policy_headings[0] if policy_headings else None,
                    "top_3_policy_headings": policy_headings,
                    "expected_policy_rank": min(expected_policy_ranks)
                    if expected_policy_ranks
                    else None,
                    "policy_top_1_correct": bool(policy_headings)
                    and policy_headings[0] in expected_policy_headings,
                }
            )
        rows.append(row)
    return score_retrieval(rows)


def score_live(rows: list[dict]) -> dict:
    count = len(rows)
    return {
        "sample_size": count,
        "team_accuracy": sum(row["team_correct"] for row in rows) / count if count else None,
        "priority_accuracy": sum(row["priority_correct"] for row in rows) / count if count else None,
        "dual_collection_citation_rate": (
            sum(row["dual_collection_citations"] for row in rows) / count if count else None
        ),
        "total_estimated_api_cost_usd": sum(row["estimated_cost_usd"] for row in rows),
        "limitations": (
            "The labels are synthetic operations scenarios. Team and priority accuracy do not "
            "establish legal correctness, complaint resolution quality, or historical-evidence relevance."
        ),
        "examples": rows,
    }


def team_labels_match(expected: str, predicted: str) -> bool:
    """Treat a trailing display-only 'team' suffix as the same routing label."""

    def normalize(value: str) -> str:
        return re.sub(r"\s+team$", "", " ".join(value.split()), flags=re.IGNORECASE).casefold()

    return normalize(expected) == normalize(predicted)


def evaluate_live(db: Session, max_cases: int, max_cost_usd: float) -> dict:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for an opt-in live benchmark")
    if settings.openai_model != "gpt-5.6-luna":
        raise RuntimeError("The cost-bounded benchmark currently supports gpt-5.6-luna only")
    if max_cases < 1 or max_cases > 8 or max_cost_usd < 0.02:
        raise ValueError("Choose 1–8 cases and a cost ceiling of at least $0.02")
    rows = []
    spent = 0.0
    for example in load_live_cases()[:max_cases]:
        # Reserve $0.02 before each run. This is a soft, not provider-enforced, ceiling.
        if (len(rows) + 1) * 0.02 > max_cost_usd or spent + 0.02 > max_cost_usd:
            break
        case = Case(id=uuid.uuid4(), product=example["product"], narrative=example["narrative"])
        result = analyze_with_openai(
            db,
            case,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            embedding_model=settings.openai_embedding_model,
            embedding_dimensions=settings.openai_embedding_dimensions,
            max_agent_turns=2,
            max_output_tokens=1000,
        )
        recommendation = result.recommendation
        spent += result.estimated_cost_usd
        rows.append(
            {
                "product": example["product"],
                "expected_team": example["expected_team"],
                "predicted_team": recommendation.classification.assigned_team,
                "team_correct": team_labels_match(
                    example["expected_team"], recommendation.classification.assigned_team
                ),
                "expected_priority": example["expected_priority"],
                "predicted_priority": recommendation.classification.priority,
                "priority_correct": (
                    recommendation.classification.priority == example["expected_priority"]
                ),
                "dual_collection_citations": (
                    {citation.collection for citation in recommendation.citations}
                    == {"historical_complaints", "operating_policies"}
                ),
                "estimated_cost_usd": result.estimated_cost_usd,
                "citation_ids": [citation.source_id for citation in recommendation.citations],
            }
        )
    return score_live(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Opt in to paid OpenAI agent calls")
    parser.add_argument("--max-cases", type=int, default=2)
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    parser.add_argument(
        "--judgments",
        type=Path,
        help="Optional expanded judgment JSON; defaults to the packaged regression set",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    with SessionLocal() as db:
        report = {"retrieval": evaluate_retrieval(db, load_judgments(args.judgments))}
        if args.live:
            report["live_agent"] = evaluate_live(db, args.max_cases, args.max_cost_usd)
    serialized = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote benchmark report to {args.output}")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
