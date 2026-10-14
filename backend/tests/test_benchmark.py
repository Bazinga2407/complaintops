from unittest.mock import Mock

import pytest

from app.db.models import Complaint
from app.services.benchmark import (
    evaluate_retrieval,
    normalized_dcg_at_k,
    parse_judgments,
    score_live,
    score_retrieval,
    team_labels_match,
)


def test_evaluation_uses_exact_top_five_query_for_graded_metrics(monkeypatch) -> None:
    db = Mock()
    anchor = Mock(embedding=[0.1, 0.2], embedding_model="test-embedding")
    complaint = Complaint(id=1, product="Rare product")
    known_relevant = Mock()
    db.get.side_effect = [anchor, complaint, known_relevant]
    scalar_result = Mock()
    scalar_result.all.return_value = []
    db.scalars.return_value = scalar_result
    requested_limits: list[int] = []

    def retrieve_candidates(*_args, limit: int, **_kwargs):
        requested_limits.append(limit)
        candidate_ids = [2, 3, 4, 5, 6] if limit == 5 else list(range(2, 12))
        return [(Complaint(id=candidate_id), 0.1) for candidate_id in candidate_ids]

    monkeypatch.setattr(
        "app.services.benchmark.retrieve_complaint_candidates",
        retrieve_candidates,
    )
    report = evaluate_retrieval(
        db,
        [
            {
                "anchor_id": 1,
                "known_relevant_id": 3,
                "judged_candidates": [
                    {"complaint_id": candidate_id, "relevance_grade": 3}
                    for candidate_id in range(2, 7)
                ],
            }
        ],
    )

    assert requested_limits == [5, 10]
    assert report["judgment_coverage_at_5"] == 1
    assert report["known_relevant_mrr_at_10"] == 0.5


def test_parse_judgments_accepts_audited_wrapper() -> None:
    assert parse_judgments(
        {"metadata": {"status": "reviewed"}, "judgments": [{"anchor_id": 1}]}
    ) == [{"anchor_id": 1}]


def test_retrieval_scores_are_named_as_incomplete_judgments() -> None:
    result = score_retrieval(
        [
            {"known_relevant_rank": 2, "policy_top_1_correct": True},
            {"known_relevant_rank": None, "policy_top_1_correct": False},
        ]
    )
    assert result["known_relevant_hit_at_10"] == 0.5
    assert result["known_relevant_mrr_at_10"] == 0.25
    assert result["policy_top_1_accuracy"] == 0.5
    assert "incomplete" in result["limitations"]


def test_retrieval_scores_judged_top_five_and_policy_top_three() -> None:
    candidates = [
        {"complaint_id": index, "relevant": index != 5}
        for index in range(1, 6)
    ]
    result = score_retrieval(
        [
            {
                "known_relevant_rank": None,
                "policy_top_1_correct": False,
                "expected_policy_rank": 2,
                "retrieved_top_5": candidates,
            }
        ]
    )

    assert result["judgment_coverage_at_5"] == 1
    assert result["judged_precision_at_5"] == 0.8
    assert result["graded_ndcg_at_5"] is not None
    assert result["policy_hit_at_3"] == 1
    assert result["policy_mrr_at_3"] == 0.5


def test_ndcg_rewards_putting_the_most_relevant_results_first() -> None:
    best_first = [
        {"relevance_grade": grade} for grade in (3, 2, 2, 1, 0)
    ]
    best_last = list(reversed(best_first))

    assert normalized_dcg_at_k(best_first) == pytest.approx(1.0)
    assert normalized_dcg_at_k(best_last) < normalized_dcg_at_k(best_first)


def test_incomplete_graded_judgments_do_not_publish_ndcg() -> None:
    result = score_retrieval(
        [
            {
                "retrieved_top_5": [
                    {"relevance_grade": 3},
                    {"relevance_grade": 2},
                    {"relevance_grade": None},
                    {"relevance_grade": 0},
                    {"relevance_grade": 0},
                ],
                "known_relevant_evaluated": False,
                "policy_ranking_evaluated": False,
            }
        ]
    )

    assert result["graded_ndcg_at_5"] is None
    assert result["graded_judgment_coverage_at_5"] == 0
    assert result["known_relevant_hit_at_10"] is None
    assert result["policy_hit_at_3"] is None


def test_ndcg_is_zero_when_no_retrieved_candidate_is_relevant() -> None:
    candidates = [{"relevance_grade": 0} for _ in range(5)]

    assert normalized_dcg_at_k(candidates) == 0


def test_live_scores_only_labeled_operational_fields() -> None:
    result = score_live(
        [
            {
                "team_correct": True,
                "priority_correct": False,
                "dual_collection_citations": True,
                "estimated_cost_usd": 0.001,
            }
        ]
    )
    assert result["team_accuracy"] == 1
    assert result["priority_accuracy"] == 0
    assert result["total_estimated_api_cost_usd"] == 0.001


def test_team_labels_ignore_display_only_team_suffix() -> None:
    assert team_labels_match("Credit Reporting", "Credit Reporting team")
    assert team_labels_match("Collections Resolution", "collections resolution TEAM")
    assert not team_labels_match("Credit Reporting", "Collections Resolution")
