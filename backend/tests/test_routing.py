from app.services.routing import preview_route


def test_debt_collection_routes_to_collections() -> None:
    result = preview_route("Debt collection", "The collector keeps calling me.")

    assert result.team == "Collections Resolution"
    assert result.priority == "standard"
    assert result.requires_human_review is True


def test_identity_theft_is_priority() -> None:
    result = preview_route("Credit reporting", "This account resulted from identity theft.")

    assert result.team == "Credit Reporting"
    assert result.priority == "priority"
    assert "Narrative mentions identity theft" in result.reasons
