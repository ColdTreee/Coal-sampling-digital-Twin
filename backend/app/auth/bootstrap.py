from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.core.config import get_settings
from app.models import Role, User, user_roles

ROLE_DESCRIPTIONS = {"administrator": "管理员", "operator": "值班人员", "readonly": "只读查看"}


def ensure_bootstrap_account(session: Session) -> None:
    for name, description in ROLE_DESCRIPTIONS.items():
        if session.scalar(select(Role.id).where(Role.name == name)) is None:
            session.add(Role(name=name, description=description))
    session.flush()
    settings = get_settings()
    user = session.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
    if user is None:
        user = User(
            username=settings.bootstrap_admin_username,
            password_hash=hash_password(settings.bootstrap_admin_password),
        )
        session.add(user)
        session.flush()
    role = session.scalar(select(Role).where(Role.name == "administrator"))
    if session.scalar(select(user_roles.c.user_id).where(
        user_roles.c.user_id == user.id, user_roles.c.role_id == role.id,
    )) is None:
        session.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
    session.commit()
