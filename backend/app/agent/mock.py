from app.db.models import Case, Complaint
from app.schemas.case import AgentRecommendation, Citation, Classification
from app.services.routing import preview_route


def _predict_issue(narrative: str, fallback: str | None) -> tuple[str, float]:
    text = narrative.lower()
    rules = (
        (("identity theft", "not mine", "do not recognize"), "Account or information is not yours"),
        (("call", "contact", "harass"), "Communication tactics"),
        (("refund", "money back"), "Problem receiving a refund"),
        (("transfer", "funds", "payment"), "Problem with a payment or transfer"),
        (("credit report", "credit score"), "Incorrect information on a credit report"),
    )
    for terms, label in rules:
        if any(term in text for term in terms):
            return label, 0.84
    return fallback or "Needs specialist classification", 0.62


def analyze_with_mock(case: Case, similar: list[Complaint]) -> AgentRecommendation:
    route = preview_route(case.product, case.narrative)
    predicted_issue, confidence = _predict_issue(case.narrative, case.issue)
    escalation_flags = route.reasons[1:]

    citations = [
        Citation(
            collection="operating_policies",
            source_id="complaint-handling-policy.md#triage",
            label="Complaint Handling Policy — Triage",
            excerpt=f"Route this product category to the {route.team} team.",
        ),
        Citation(
            collection="operating_policies",
            source_id="complaint-handling-policy.md#human-approval",
            label="Complaint Handling Policy — Human approval",
            excerpt="A human operator must approve or edit the recommendation.",
        ),
    ]
    citations.extend(
        Citation(
            collection="historical_complaints",
            source_id=str(complaint.id),
            label=f"CFPB complaint {complaint.id}",
            excerpt=(complaint.narrative or "No public narrative")[:240],
        )
        for complaint in similar
    )

    recommended_actions = [
        f"Assign the case to {route.team} for review.",
        "Compare the account and dispute history with the consumer's narrative.",
        "Prepare a plain-language acknowledgement and list any additional evidence needed.",
    ]
    if route.priority == "priority":
        recommended_actions.insert(0, "Place the case in the priority-review queue.")

    return AgentRecommendation(
        summary=(
            f"The consumer reports an issue involving {case.product.lower()}"
            + (f" and {case.company}." if case.company else ".")
        ),
        classification=Classification(
            product=case.product,
            issue=predicted_issue,
            assigned_team=route.team,
            priority=route.priority,
            confidence=confidence,
            escalation_flags=escalation_flags,
        ),
        recommended_actions=recommended_actions,
        rationale=[*route.reasons, f"Found {len(similar)} comparable historical complaints."],
        citations=citations,
        provider="mock",
    )
