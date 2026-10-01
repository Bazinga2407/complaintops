import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.core.security import AdminDep, DbDep
from app.db.models import User
from app.schemas.user import UserInvite, UserList, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserList)
def list_users(_: AdminDep, db: DbDep) -> UserList:
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return UserList(items=list(users))


@router.post("/invitations", response_model=UserRead, status_code=201)
def invite_user(payload: UserInvite, _: AdminDep, db: DbDep) -> User:
    existing = db.scalar(select(User).where(func.lower(User.email) == payload.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    user = User(
        email=payload.email,
        display_name=payload.display_name.strip() if payload.display_name else None,
        role=payload.role,
        status="invited",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: uuid.UUID, payload: UserUpdate, admin: AdminDep, db: DbDep) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if admin.id == user.id and (
        payload.status == "disabled" or (payload.role is not None and payload.role != "admin")
    ):
        raise HTTPException(status_code=400, detail="You cannot remove your own administrator access")
    if payload.role is not None:
        user.role = payload.role
    if payload.status is not None:
        user.status = payload.status
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or None
    db.commit()
    db.refresh(user)
    return user
