from app.services.benchmark import score_live, score_retrieval, team_labels_match


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
    assert result["policy_hit_at_3"] == 1
    assert result["policy_mrr_at_3"] == 0.5


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
