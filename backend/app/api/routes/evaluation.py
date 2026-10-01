from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import require_operator
from app.db.models import AnalysisRun, ReviewAction
from app.db.session import get_db
from app.schemas.case import BaselineEvaluation, EvaluationSummary, RetrievalEvaluation
from app.services.baseline import evaluate_mock_routing
from app.services.benchmark import evaluate_retrieval
from app.services.evaluation import summarize_analyses

router = APIRouter(
    prefix="/evaluation", tags=["evaluation"], dependencies=[Depends(require_operator)]
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/summary", response_model=EvaluationSummary)
def evaluation_summary(db: DbSession) -> EvaluationSummary:
    runs = list(db.scalars(select(AnalysisRun)).all())
    reviews = list(db.scalars(select(ReviewAction)).all())
    return summarize_analyses(runs, reviews)


@router.get("/mock-baseline", response_model=BaselineEvaluation)
def mock_baseline() -> BaselineEvaluation:
    return evaluate_mock_routing()


@router.get("/retrieval-benchmark", response_model=RetrievalEvaluation)
def retrieval_benchmark(db: DbSession) -> dict:
    """Run the free, read-only benchmark against the current pgvector snapshot."""
    return evaluate_retrieval(db)
