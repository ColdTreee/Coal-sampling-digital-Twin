import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.security import AuthenticatedUser, require_roles
from app.models import AuditLog
from app.models import AlarmRule, Device, SensorPoint
from app.schemas import AlarmRuleCreate, DeviceCreate, DeviceRead, SensorPointCreate

router = APIRouter(prefix="/master-data", tags=["master-data"])


@router.get("/devices", response_model=list[DeviceRead])
def list_devices(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db),
) -> list[Device]:
    return list(session.scalars(select(Device).where(Device.is_active.is_(True))
                                .order_by(Device.device_code).offset(offset).limit(limit)))


@router.get("/sensor-points")
def list_sensor_points(
    device_id: UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
):
    query = select(SensorPoint).where(SensorPoint.is_active.is_(True))
    if device_id:
        query = query.where(SensorPoint.device_id == device_id)
    return list(session.scalars(query.order_by(SensorPoint.point_code).offset(offset).limit(limit)))


@router.post("/devices", response_model=DeviceRead, status_code=201)
def create_device(
    body: DeviceCreate, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator")),
) -> Device:
    device = Device(**body.model_dump())
    session.add(device)
    session.add(AuditLog(actor_id=identity.user.id, action="device.create",
                         target_type="device", outcome="success",
                         change_summary={"device_code": body.device_code}))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="设备编号或场景映射键已存在") from exc
    session.refresh(device)
    return device


@router.post("/sensor-points", status_code=201)
def create_sensor_point(
    body: SensorPointCreate, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator")),
) -> dict[str, str]:
    device = session.get(Device, body.device_id)
    if device is None or not device.is_active:
        raise HTTPException(status_code=404, detail="设备不存在或已停用")
    point = SensorPoint(**body.model_dump())
    session.add(point)
    session.add(AuditLog(actor_id=identity.user.id, action="sensor_point.create",
                         target_type="sensor_point", outcome="success",
                         change_summary={"point_code": body.point_code}))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="点位编号已存在") from exc
    return {"id": str(point.id), "point_code": point.point_code}


@router.post("/alarm-rules", status_code=201)
def create_alarm_rule(
    body: AlarmRuleCreate, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator")),
) -> dict[str, str]:
    supported = {"threshold", "process_timeout", "missing_action", "state_inconsistency", "data_quality"}
    kind = body.condition.get("kind")
    if not isinstance(kind, str) or kind not in supported:
        raise HTTPException(status_code=422, detail="不支持的规则类型")
    if kind == "threshold":
        if body.condition.get("operator", "gt") not in ("lt", "gt"):
            raise HTTPException(422, "阈值运算符必须为 lt 或 gt")
        validate_number(body.condition, "threshold", required=False)
    if kind == "process_timeout":
        validate_number(body.condition, "max_seconds", minimum=0)
    rule = AlarmRule(**body.model_dump())
    session.add(rule)
    session.add(AuditLog(actor_id=identity.user.id, action="alarm_rule.create",
                         target_type="alarm_rule", outcome="success",
                         change_summary={"rule_code": body.rule_code}))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="规则编号已存在") from exc
    return {"id": str(rule.id), "rule_code": rule.rule_code}


def validate_number(condition: dict, name: str, *, minimum=None, required=True) -> None:
    if not required and name not in condition:
        return
    value = condition.get(name)
    if type(value) not in (int, float) or not math.isfinite(value) or (minimum is not None and value < minimum):
        raise HTTPException(422, f"规则参数 {name} 无效")
