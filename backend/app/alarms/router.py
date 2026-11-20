from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.security import AuthenticatedUser, require_roles
from app.models import Alarm, AlarmAction, AuditLog
from app.schemas import AlarmActionCreate

router = APIRouter(prefix="/alarms", tags=["alarms"])


@router.get("")
def list_alarms(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    severity: str | None = None,
    session: Session = Depends(get_db),
) -> dict:
    query = select(Alarm)
    if status:
        query = query.where(Alarm.status == status)
    if severity:
        query = query.where(Alarm.severity == severity)
    alarms = list(session.scalars(query.order_by(Alarm.first_triggered_at.desc()).offset(offset).limit(limit)))
    return {
        "items": [
            {"id": alarm.id, "source_type": alarm.source_type, "severity": alarm.severity,
             "status": alarm.status, "first_triggered_at": alarm.first_triggered_at,
             "trigger_condition": alarm.trigger_condition,
             "related_object_type": alarm.related_object_type,
             "related_object_id": alarm.related_object_id,
             "suggested_action": _suggested_action(alarm.trigger_condition)}
            for alarm in alarms
        ],
        "offset": offset,
        "limit": limit,
    }


def _suggested_action(condition: dict) -> str:
    reason = condition.get("reason")
    if reason == "unknown_device_or_point":
        return "核对设备台账、点位编号及设备归属。"
    if reason in {"timestamp_in_future", "timestamp_too_old"}:
        return "核对采集端时钟、时区和补传数据的采集时间。"
    if reason == "duplicate_message":
        return "核对来源端消息编号和补传记录。"
    if reason in {"below_range", "above_range"}:
        return "核对传感器量程、单位和原始采集值。"
    if "threshold" in condition or "point_code" in condition:
        return "核对设备工况和测点阈值，确认是否需要现场检查。"
    return "检查关联设备或工艺环节，并记录核查结果。"


@router.post("/{alarm_id}/actions", status_code=201)
def create_alarm_action(
    alarm_id: UUID,
    body: AlarmActionCreate,
    session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
) -> dict[str, str]:
    alarm = session.scalar(select(Alarm).where(Alarm.id == alarm_id).with_for_update())
    if alarm is None:
        raise HTTPException(status_code=404, detail="告警不存在")
    now = datetime.now(timezone.utc)
    if body.action == "confirm":
        if alarm.status != "open":
            raise HTTPException(status_code=409, detail="只有未确认告警可以确认")
        alarm.status = "acknowledged"
        alarm.confirmed_at = now
    elif body.action == "close":
        if alarm.status not in {"open", "acknowledged"}:
            raise HTTPException(status_code=409, detail="告警已关闭")
        alarm.status = "closed"
        alarm.closed_at = now
    session.add(AlarmAction(
        alarm_id=alarm.id, actor_id=identity.user.id, action_type=body.action, note=body.note,
    ))
    session.add(AuditLog(actor_id=identity.user.id, action="alarm." + body.action,
                         target_type="alarm", target_id=str(alarm.id), outcome="success",
                         change_summary={"status": alarm.status, "note": body.note}))
    session.commit()
    return {"alarm_id": str(alarm.id), "status": alarm.status}
