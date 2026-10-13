from app.services.benchmark_export import AnchorCandidate, select_diverse_anchors


def _candidate(complaint_id: int, product: str, issue: str) -> AnchorCandidate:
    return AnchorCandidate(
        complaint_id=complaint_id,
        product=product,
        issue=issue,
        narrative=f"Narrative {complaint_id}",
    )


def test_anchor_selection_is_reproducible_and_diverse() -> None:
    candidates = [
        _candidate(1, "Debt collection", "Unknown debt"),
        _candidate(2, "Debt collection", "Unknown debt"),
        _candidate(3, "Debt collection", "Communication tactics"),
        _candidate(4, "Mortgage", "Foreclosure"),
        _candidate(5, "Mortgage", "Foreclosure"),
        _candidate(6, "Credit reporting", "Identity theft"),
    ]

    first = select_diverse_anchors(candidates, count=4, seed="fixed")
    second = select_diverse_anchors(candidates, count=4, seed="fixed")

    assert [item.complaint_id for item in first] == [item.complaint_id for item in second]
    assert len({(item.product, item.issue) for item in first}) == 4
