from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: DbSession) -> dict[str, str]:
    try:
        required_tables = db.execute(
            text(
                "SELECT to_regclass('public.complaints'), to_regclass('public.cases'), "
                "to_regclass('public.users')"
            )
        ).one()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    if any(table is None for table in required_tables):
        raise HTTPException(status_code=503, detail="Database schema is not initialized")
    return {"status": "ready", "database": "connected"}
