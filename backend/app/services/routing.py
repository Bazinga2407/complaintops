from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingRecommendation:
    team: str
    priority: str
    reasons: list[str]
    requires_human_review: bool = True


TEAM_BY_PRODUCT = {
    "credit reporting": "Credit Reporting",
    "debt collection": "Collections Resolution",
    "money transfer": "Payments",
    "virtual currency": "Payments",
}

PRIORITY_TERMS = {
    "foreclosure": "Narrative mentions foreclosure",
    "identity theft": "Narrative mentions identity theft",
    "stolen identity": "Narrative mentions possible identity theft",
    "cannot access": "Narrative may describe loss of access to funds",
    "legal action": "Narrative mentions legal action",
}


def preview_route(product: str, narrative: str | None) -> RoutingRecommendation:
    product_lower = product.lower()
    team = next(
        (team for keyword, team in TEAM_BY_PRODUCT.items() if keyword in product_lower),
        "General Resolution",
    )

    narrative_lower = (narrative or "").lower()
    priority_reasons = [
        reason for keyword, reason in PRIORITY_TERMS.items() if keyword in narrative_lower
    ]
    priority = "priority" if priority_reasons else "standard"
    reasons = [f"Product routes to {team}", *priority_reasons]

    return RoutingRecommendation(team=team, priority=priority, reasons=reasons)
