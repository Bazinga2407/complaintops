import pytest

from app.services.benchmark_compile import compile_judgments


def candidates() -> list[dict]:
    return [
        {
            "anchor_id": 10,
            "expected_policy_headings": [],
            "judged_candidates": [
                {"complaint_id": 20, "relevance_grade": None, "reason": ""},
                {"complaint_id": 30, "relevance_grade": None, "reason": ""},
            ],
        }
    ]


def labels() -> dict:
    return {
        "schema_version": 1,
        "review_status": "provisional",
        "anchors": [
            {
                "anchor_id": 10,
                "expected_policy_headings": ["Triage"],
                "candidate_grades": {"20": 3, "30": 0},
            }
        ],
    }


def test_compile_applies_complete_labels_and_metadata() -> None:
    result = compile_judgments(candidates(), labels())

    assert result["metadata"]["anchor_count"] == 1
    assert result["metadata"]["candidate_judgment_count"] == 2
    assert result["judgments"][0]["expected_policy_headings"] == ["Triage"]
    assert [
        item["relevance_grade"]
        for item in result["judgments"][0]["judged_candidates"]
    ] == [3, 0]
    assert all(item["reason"] for item in result["judgments"][0]["judged_candidates"])


def test_compile_rejects_stale_candidate_labels() -> None:
    stale = labels()
    stale["anchors"][0]["candidate_grades"] = {"20": 3, "99": 0}

    with pytest.raises(ValueError, match="candidate labels do not match"):
        compile_judgments(candidates(), stale)
