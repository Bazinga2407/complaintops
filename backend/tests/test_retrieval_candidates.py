from unittest.mock import Mock

from app.db.models import Complaint
from app.services.retrieval_candidates import retrieve_complaint_candidates


def _result(rows: list[tuple[Complaint, float]]) -> Mock:
    result = Mock()
    result.all.return_value = rows
    return result


def test_sparse_product_candidates_are_backfilled_without_duplicates() -> None:
    db = Mock()
    product_match = Complaint(id=2, product="Rare product")
    global_match_one = Complaint(id=3, product="Another product")
    global_match_two = Complaint(id=4, product="Another product")
    db.execute.side_effect = [
        _result([(product_match, 0.1)]),
        _result([(global_match_one, 0.2), (global_match_two, 0.3)]),
    ]

    matches = retrieve_complaint_candidates(
        db,
        anchor_id=1,
        product="Rare product",
        anchor_embedding=[0.1, 0.2],
        embedding_model="test-embedding",
        limit=3,
    )

    assert [complaint.id for complaint, _ in matches] == [2, 3, 4]
    assert db.execute.call_count == 2


def test_full_product_candidates_do_not_query_global_fallback() -> None:
    db = Mock()
    db.execute.return_value = _result(
        [
            (Complaint(id=2, product="Common product"), 0.1),
            (Complaint(id=3, product="Common product"), 0.2),
        ]
    )

    matches = retrieve_complaint_candidates(
        db,
        anchor_id=1,
        product="Common product",
        anchor_embedding=[0.1, 0.2],
        embedding_model="test-embedding",
        limit=2,
    )

    assert [complaint.id for complaint, _ in matches] == [2, 3]
    db.execute.assert_called_once()
