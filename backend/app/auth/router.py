from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import (
    AuthenticatedUser,
    create_token,
    hash_password,
    require_roles,
    verify_password,
)
from app.core.database import get_db
from app.models import AuditLog, Role, User, user_roles
from app.schemas import UserCreate

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_db)):
    user = session.scalar(select(User).where(User.username == form.username))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        session.add(AuditLog(
            actor_id=user.id if user else None, action="auth.login",
            target_type="user", target_id=str(user.id) if user else None,
            outcome="failure", change_summary={"username": form.username},
        ))
        session.commit()
        raise HTTPException(401, "用户名或密码错误", headers={"WWW-Authenticate": "Bearer"})
    roles = list(session.scalars(
        select(Role.name).join(user_roles, Role.id == user_roles.c.role_id)
        .where(user_roles.c.user_id == user.id)
    ))
    session.add(AuditLog(
        actor_id=user.id, action="auth.login", target_type="user",
        target_id=str(user.id), outcome="success", change_summary={},
    ))
    session.commit()
    return {"access_token": create_token(user, roles), "token_type": "bearer",
            "username": user.username, "roles": roles}


@router.get("/me")
def me(identity: AuthenticatedUser = Depends(require_roles(
    "administrator", "operator", "readonly",
))):
    return {"username": identity.user.username, "roles": sorted(identity.roles)}


@router.post("/users", status_code=201)
def create_user(
    body: UserCreate,
    session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator")),
):
    role = session.scalar(select(Role).where(Role.name == body.role))
    if role is None:
        raise HTTPException(422, "角色不存在")
    user = User(username=body.username, password_hash=hash_password(body.password))
    session.add(user)
    try:
        session.flush()
        session.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
        session.add(AuditLog(
            actor_id=identity.user.id, action="user.create", target_type="user",
            target_id=str(user.id), outcome="success",
            change_summary={"username": user.username, "role": body.role},
        ))
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "用户名已存在") from exc
    return {"id": str(user.id), "username": user.username, "role": body.role}
