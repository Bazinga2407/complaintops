from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.agent.mock import analyze_with_mock
from app.api.routes.cases import review_analysis
from app.core.security import AuthenticatedUser
from app.db.models import AnalysisRun, Case, ReviewAction
from app.schemas.case import AgentRecommendation, ReviewCreate


class FakeSession:
    def __init__(self, run: AnalysisRun) -> None:
        self.run = run
        self.added: ReviewAction | None = None
        self.scalar_calls = 0
        self.statements: list[object] = []

    def get(self, _model: type[AnalysisRun], _id: object) -> AnalysisRun:
        return self.run

    def scalar(self, statement: object) -> object:
        self.statements.append(statement)
        self.scalar_calls += 1
        return self.run if self.scalar_calls == 1 else self.run.id

    def add(self, review: ReviewAction) -> None:
        self.added = review

    def commit(self) -> None:
        pass

    def refresh(self, _review: ReviewAction) -> None:
        pass


def make_run() -> AnalysisRun:
    case = Case(
        id=uuid4(),
        product="Debt collection",
        narrative="A collector called about an account I do not recognize.",
        status="awaiting_review",
    )
    recommendation = analyze_with_mock(case, [])
    return AnalysisRun(
        id=uuid4(),
        case=case,
        status="completed",
        provider="mock",
        recommendation=recommendation.model_dump(),
    )


def reviewer() -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid4(),
        email="reviewer@example.com",
        display_name="Authenticated Reviewer",
        role="reviewer",
        auth_mode="oidc",
    )


def test_edit_persists_review_and_updates_case_routing() -> None:
    run = make_run()
    db = FakeSession(run)
    edited = AgentRecommendation.model_validate(run.recommendation)
    edited.summary = "The consumer disputes a debt collection account."
    edited.classification.assigned_team = "Specialist Collections"
    edited.classification.priority = "priority"

    review = review_analysis(
        run.id,
        ReviewCreate(action="edited", edited_recommendation=edited),
        db,  # type: ignore[arg-type]
        reviewer(),
    )

    assert review.action == "edited"
    assert review.reviewer == "Authenticated Reviewer"
    assert review.reviewer_user_id is not None
    assert review.edited_recommendation["summary"] == edited.summary
    assert run.case.status == "approved"
    assert run.case.assigned_team == "Specialist Collections"
    assert run.case.priority == "priority"
    assert db.statements[0]._for_update_arg is not None  # type: ignore[attr-defined]


def test_edit_cannot_change_evidence() -> None:
    run = make_run()
    edited = AgentRecommendation.model_validate(run.recommendation)
    edited.citations[0].source_id = "invented-evidence"

    with pytest.raises(HTTPException) as error:
        review_analysis(
            run.id,
            ReviewCreate(action="edited", edited_recommendation=edited),
            FakeSession(run),  # type: ignore[arg-type]
            reviewer(),
        )

    assert error.value.status_code == 400
    assert run.case.status == "awaiting_review"


def test_review_cannot_be_repeated_after_approval() -> None:
    run = make_run()
    run.case.status = "approved"

    with pytest.raises(HTTPException) as error:
        review_analysis(
            run.id,
            ReviewCreate(action="rejected"),
            FakeSession(run),  # type: ignore[arg-type]
            reviewer(),
        )

    assert error.value.status_code == 409
