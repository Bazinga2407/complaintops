from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import require_operator
from app.db.models import Complaint
from app.db.session import get_db
from app.schemas.complaint import ComplaintList, ComplaintSummary, RoutePreview
from app.services.routing import preview_route

router = APIRouter(
    prefix="/complaints", tags=["complaints"], dependencies=[Depends(require_operator)]
)
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ComplaintList)
def list_complaints(
    db: DbSession,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    product: str | None = None,
    state: str | None = Query(default=None, min_length=2, max_length=2),
) -> ComplaintList:
    filters = []
    if product:
        filters.append(Complaint.product == product)
    if state:
        filters.append(Complaint.state == state.upper())

    total = db.scalar(select(func.count()).select_from(Complaint).where(*filters)) or 0
    rows = db.scalars(
        select(Complaint)
        .where(*filters)
        .order_by(Complaint.date_received.desc(), Complaint.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return ComplaintList(items=list(rows), total=total, limit=limit, offset=offset)


@router.get("/{complaint_id}", response_model=ComplaintSummary)
def get_complaint(complaint_id: int, db: DbSession) -> Complaint:
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    return complaint


@router.get("/{complaint_id}/route-preview", response_model=RoutePreview)
def get_route_preview(complaint_id: int, db: DbSession) -> RoutePreview:
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    recommendation = preview_route(complaint.product, complaint.narrative)
    return RoutePreview(
        team=recommendation.team,
        priority=recommendation.priority,
        reasons=recommendation.reasons,
        requires_human_review=recommendation.requires_human_review,
    )
