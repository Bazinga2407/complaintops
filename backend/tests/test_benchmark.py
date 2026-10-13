import pytest

from app.services.benchmark import (
    normalized_dcg_at_k,
    score_live,
    score_retrieval,
    team_labels_match,
)


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
