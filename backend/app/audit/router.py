from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import AuthenticatedUser, require_roles
from app.core.database import get_db
from app.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/logs")
def list_audit_logs(
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
    action: str | None = None, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator")),
):
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action == action)
    rows = session.scalars(query.order_by(
        AuditLog.occurred_at.desc(), AuditLog.id.desc(),
    ).offset(offset).limit(limit))
    return {"items": [{
        "id": row.id, "actor_id": row.actor_id, "action": row.action,
        "target_type": row.target_type, "target_id": row.target_id,
        "occurred_at": row.occurred_at, "outcome": row.outcome,
        "change_summary": row.change_summary,
    } for row in rows], "offset": offset, "limit": limit}
