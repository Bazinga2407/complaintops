import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent.mock import analyze_with_mock
from app.agent.openai_agent import analyze_with_openai
from app.core.config import get_settings
from app.core.security import ReviewerDep, limit_analysis, require_operator
from app.db.models import AnalysisRun, Case, Complaint, ReviewAction
from app.db.session import get_db
from app.schemas.case import (
    AnalysisRead,
    CaseCreate,
    CaseCreated,
    CaseList,
    CaseRead,
    ReviewCreate,
    ReviewHistory,
    ReviewRead,
)
from app.services.privacy import redact_sensitive_text

router = APIRouter(prefix="/cases", tags=["cases"], dependencies=[Depends(require_operator)])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=CaseList)
def list_cases(db: DbSession) -> CaseList:
    rows = db.scalars(select(Case).order_by(Case.created_at.desc())).all()
    total = db.scalar(select(func.count()).select_from(Case)) or 0
    return CaseList(items=list(rows), total=total)


@router.post("", response_model=CaseCreated, status_code=201)
def create_case(payload: CaseCreate, db: DbSession) -> CaseCreated:
    if not payload.consent_to_store_redacted_text:
        raise HTTPException(
            status_code=400,
            detail="Consent is required before the redacted narrative can be stored.",
        )
    redaction = redact_sensitive_text(payload.narrative)
    case = Case(
        source="manual",
        product=payload.product.strip(),
        narrative=redaction.text.strip(),
        company=payload.company.strip() if payload.company else None,
        state=payload.state,
        redaction_count=redaction.count,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return CaseCreated(
        **CaseRead.model_validate(case).model_dump(),
        privacy_message=(
            f"Stored the redacted narrative; removed {redaction.count} sensitive value(s)."
        ),
    )


@router.post("/from-cfpb/{complaint_id}", response_model=CaseCreated, status_code=201)
def create_case_from_cfpb(complaint_id: int, db: DbSession) -> CaseCreated:
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Historical complaint not found")
    if not complaint.narrative:
        raise HTTPException(status_code=400, detail="Historical complaint has no public narrative")
    existing = db.scalar(select(Case).where(Case.source_complaint_id == complaint_id))
    if existing:
        raise HTTPException(status_code=409, detail="A case already exists for this complaint")

    case = Case(
        source="cfpb",
        source_complaint_id=complaint.id,
        product=complaint.product,
        issue=complaint.issue,
        narrative=complaint.narrative,
        company=complaint.company,
        state=complaint.state,
        redaction_count=0,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return CaseCreated(
        **CaseRead.model_validate(case).model_dump(),
        privacy_message="Created from a CFPB-published, scrubbed narrative.",
    )


@router.get("/{case_id}", response_model=CaseRead)
def get_case(case_id: uuid.UUID, db: DbSession) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/{case_id}/analyses/latest", response_model=AnalysisRead)
def get_latest_analysis(case_id: uuid.UUID, db: DbSession) -> AnalysisRead:
    run = db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.case_id == case_id, AnalysisRun.status == "completed")
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    if run is None or run.recommendation is None:
        raise HTTPException(status_code=404, detail="No completed analysis found")
    latest_review = db.scalar(
        select(ReviewAction)
        .where(ReviewAction.analysis_run_id == run.id)
        .order_by(ReviewAction.created_at.desc(), ReviewAction.id.desc())
        .limit(1)
    )
    recommendation = (
        latest_review.edited_recommendation
        if latest_review is not None and latest_review.action == "edited"
        else run.recommendation
    )
    return AnalysisRead(
        id=run.id,
        case_id=run.case_id,
        status=run.status,
        recommendation=recommendation,
        model=run.model,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        estimated_cost_usd=(
            float(run.estimated_cost_usd) if run.estimated_cost_usd is not None else None
        ),
        tool_trace=run.tool_trace,
        created_at=run.created_at,
    )


@router.get("/{case_id}/reviews", response_model=ReviewHistory)
def get_case_reviews(case_id: uuid.UUID, db: DbSession) -> ReviewHistory:
    if db.get(Case, case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")
    reviews = db.scalars(
        select(ReviewAction)
        .join(AnalysisRun, ReviewAction.analysis_run_id == AnalysisRun.id)
        .where(AnalysisRun.case_id == case_id)
        .order_by(ReviewAction.created_at.desc(), ReviewAction.id.desc())
    ).all()
    return ReviewHistory(items=list(reviews))


@router.post(
    "/{case_id}/analyze",
    response_model=AnalysisRead,
    status_code=201,
    dependencies=[Depends(limit_analysis)],
)
def analyze_case(case_id: uuid.UUID, db: DbSession) -> AnalysisRead:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    settings = get_settings()
    provider = settings.agent_provider.strip().lower()
    if provider not in {"mock", "openai"}:
        raise HTTPException(status_code=500, detail="Unsupported AGENT_PROVIDER setting")
    api_key = (settings.openai_api_key or "").strip()
    if provider == "openai" and not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured")

    run = AnalysisRun(
        case_id=case.id,
        status="running",
        provider=provider,
        model=settings.openai_model if provider == "openai" else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        if provider == "openai":
            agent_result = analyze_with_openai(
                db,
                case,
                api_key=api_key,
                model=settings.openai_model.strip() or "gpt-5.6-luna",
                embedding_model=settings.openai_embedding_model,
                embedding_dimensions=settings.openai_embedding_dimensions,
                max_agent_turns=settings.openai_max_agent_turns,
                max_output_tokens=settings.openai_agent_max_output_tokens,
            )
            recommendation = agent_result.recommendation
            tool_trace = agent_result.tool_trace
            prompt_tokens = agent_result.input_tokens
            completion_tokens = agent_result.output_tokens
            estimated_cost_usd = agent_result.estimated_cost_usd
            model = agent_result.model
        else:
            similar = list(
                db.scalars(
                    select(Complaint)
                    .where(
                        Complaint.product == case.product,
                        Complaint.narrative.is_not(None),
                        Complaint.id != case.source_complaint_id,
                    )
                    .order_by(Complaint.date_received.desc())
                    .limit(3)
                ).all()
            )
            recommendation = analyze_with_mock(case, similar)
            tool_trace = [
                {"tool": "classify_complaint", "status": "completed"},
                {
                    "tool": "search_similar_complaints",
                    "status": "completed",
                    "result_count": len(similar),
                },
                {
                    "tool": "search_operating_policies",
                    "status": "completed",
                    "result_count": 2,
                },
                {"tool": "create_recommendation", "status": "completed"},
            ]
            prompt_tokens = None
            completion_tokens = None
            estimated_cost_usd = 0.0
            model = None
    except Exception as error:
        db.rollback()
        run = db.get(AnalysisRun, run.id)
        if run is not None:
            run.status = "failed"
            run.tool_trace = [{"status": "failed", "error_type": type(error).__name__}]
            run.completed_at = datetime.now(UTC)
            db.commit()
        raise HTTPException(status_code=502, detail="Agent analysis failed") from error

    case.issue = recommendation.classification.issue
    case.assigned_team = recommendation.classification.assigned_team
    case.priority = recommendation.classification.priority
    case.classification_confidence = recommendation.classification.confidence
    case.status = "awaiting_review"

    run.status = "completed"
    run.provider = recommendation.provider
    run.model = model
    run.classification = recommendation.classification.model_dump()
    run.recommendation = recommendation.model_dump()
    run.citations = [citation.model_dump() for citation in recommendation.citations]
    run.tool_trace = tool_trace
    run.prompt_tokens = prompt_tokens
    run.completion_tokens = completion_tokens
    run.estimated_cost_usd = estimated_cost_usd
    run.completed_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return AnalysisRead(
        id=run.id,
        case_id=case.id,
        status=run.status,
        recommendation=recommendation,
        model=run.model,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        estimated_cost_usd=(
            float(run.estimated_cost_usd) if run.estimated_cost_usd is not None else None
        ),
        tool_trace=run.tool_trace,
        created_at=run.created_at,
    )


@router.post("/analyses/{analysis_id}/reviews", response_model=ReviewRead, status_code=201)
def review_analysis(
    analysis_id: uuid.UUID,
    payload: ReviewCreate,
    db: DbSession,
    reviewer: ReviewerDep,
) -> ReviewAction:
    run = db.scalar(
        select(AnalysisRun).where(AnalysisRun.id == analysis_id).with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    if run.status != "completed" or run.recommendation is None:
        raise HTTPException(status_code=409, detail="Only completed analyses can be reviewed")
    latest_run = db.scalar(
        select(AnalysisRun.id)
        .where(AnalysisRun.case_id == run.case_id, AnalysisRun.status == "completed")
        .order_by(AnalysisRun.created_at.desc())
        .limit(1)
    )
    if latest_run != run.id or run.case.status not in {"new", "awaiting_review"}:
        raise HTTPException(
            status_code=409, detail="Only the latest pending analysis can be reviewed"
        )
    if payload.action == "edited" and payload.edited_recommendation is None:
        raise HTTPException(status_code=400, detail="Edited reviews require a recommendation")
    if payload.action != "edited" and payload.edited_recommendation is not None:
        raise HTTPException(status_code=400, detail="Only edited reviews accept a recommendation")
    if payload.edited_recommendation is not None:
        original = run.recommendation
        edited = payload.edited_recommendation.model_dump()
        permitted = deepcopy(original)
        permitted["summary"] = edited["summary"]
        permitted["recommended_actions"] = edited["recommended_actions"]
        permitted["classification"]["assigned_team"] = edited["classification"]["assigned_team"]
        permitted["classification"]["priority"] = edited["classification"]["priority"]
        if (
            edited != permitted
            or len(edited["summary"].strip()) < 10
            or len(edited["summary"]) > 2_000
            or not 2 <= len(edited["classification"]["assigned_team"].strip()) <= 120
            or not 1 <= len(edited["recommended_actions"]) <= 15
            or any(
                not action.strip() or len(action) > 1_000
                for action in edited["recommended_actions"]
            )
        ):
            raise HTTPException(
                status_code=400,
                detail="Only summary, assigned team, priority, and actions may be edited",
            )

    review = ReviewAction(
        analysis_run_id=run.id,
        action=payload.action,
        reviewer=reviewer.display_name,
        reviewer_user_id=reviewer.id,
        edited_recommendation=(
            payload.edited_recommendation.model_dump()
            if payload.edited_recommendation is not None
            else None
        ),
        notes=payload.notes,
    )
    if payload.action == "edited" and payload.edited_recommendation is not None:
        classification = payload.edited_recommendation.classification
        run.case.issue = classification.issue
        run.case.assigned_team = classification.assigned_team
        run.case.priority = classification.priority
        run.case.classification_confidence = classification.confidence
    run.case.status = "rejected" if payload.action == "rejected" else "approved"
    db.add(review)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This analysis has already been reviewed") from error
    db.refresh(review)
    return review
