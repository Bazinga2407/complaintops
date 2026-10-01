from datetime import date

from app.agent.mock import analyze_with_mock
from app.agent.openai_agent import _deduplicate_citations, _model_cost
from app.db.models import Case, Complaint
from app.schemas.case import Citation


def test_mock_agent_returns_cited_human_review_recommendation() -> None:
    case = Case(
        product="Credit reporting",
        narrative="An account caused by identity theft is still on my credit report.",
    )
    historical = Complaint(
        id=123,
        date_received=date(2025, 1, 1),
        product="Credit reporting",
        issue="Incorrect information",
        narrative="An unfamiliar account appeared on my report.",
        company="Example Bureau",
        source_payload={},
    )

    result = analyze_with_mock(case, [historical])

    assert result.classification.assigned_team == "Credit Reporting"
    assert result.classification.priority == "priority"
    assert result.requires_human_review is True
    assert {citation.collection for citation in result.citations} == {
        "historical_complaints",
        "operating_policies",
    }


def test_live_agent_cost_and_citations_are_bounded() -> None:
    citations = [
        Citation(
            collection="historical_complaints",
            source_id=str(index),
            label=f"Complaint {index}",
            excerpt="Evidence",
        )
        for index in range(7)
    ]
    citations.extend(
        Citation(
            collection="operating_policies",
            source_id=f"policy-{index}",
            label=f"Policy {index}",
            excerpt="Requirement",
        )
        for index in range(5)
    )

    grounded = _deduplicate_citations(citations)

    assert len([item for item in grounded if item.collection == "historical_complaints"]) == 5
    assert len([item for item in grounded if item.collection == "operating_policies"]) == 3
    assert _model_cost("gpt-5.6-luna", 1_000_000, 1_000_000) == 1.4
