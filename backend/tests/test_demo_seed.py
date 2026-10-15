from unittest.mock import Mock

from app.services.demo_seed import (
    DEMO_CASES,
    demo_analysis_id,
    demo_case_id,
    demo_case_ids,
    seed_demo_cases,
)


def test_demo_ids_are_stable_and_unique() -> None:
    first = demo_case_ids()
    second = demo_case_ids()

    assert first == second
    assert len(first) == len(set(first)) == len(DEMO_CASES)
    assert all(demo_case_id(spec.key) != demo_analysis_id(spec.key) for spec in DEMO_CASES)


def test_demo_set_exercises_every_review_queue() -> None:
    statuses = {spec.final_status for spec in DEMO_CASES}

    assert statuses == {"awaiting_review", "approved", "rejected"}
    assert sum(spec.final_status == "awaiting_review" for spec in DEMO_CASES) >= 3
    assert all("demo" in spec.company.lower() for spec in DEMO_CASES)


def test_seed_builds_complete_idempotent_case_graphs() -> None:
    db = Mock()
    empty_result = Mock()
    empty_result.all.return_value = []
    db.scalars.return_value = empty_result

    result = seed_demo_cases(db)

    cases = [call.args[0] for call in db.add.call_args_list]
    assert result.created == len(DEMO_CASES)
    assert result.skipped == 0
    assert len(cases) == len(DEMO_CASES)
    assert all(len(case.analyses) == 1 for case in cases)
    assert sum(bool(case.analyses[0].review_actions) for case in cases) == 2
    db.commit.assert_called_once()
