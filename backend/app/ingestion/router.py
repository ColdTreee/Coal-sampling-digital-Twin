from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alarms.service import (
    add_alarm,
    check_message_time,
    evaluate_event_rules,
    evaluate_telemetry,
)
from app.core.database import get_db
from app.auth.security import AuthenticatedUser, require_roles
from app.models import CoalBatch, Device, Event, Sample, SamplingTask, SensorPoint, TelemetryPoint
from app.schemas import EventMessage, TelemetryBatch, TelemetryMessage

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/telemetry")
def ingest_telemetry(
    payload: TelemetryMessage | TelemetryBatch,
    session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
) -> dict:
    messages = payload.messages if isinstance(payload, TelemetryBatch) else [payload]
    results = []
    for message in messages:
        existing = session.scalar(select(TelemetryPoint).where(
            TelemetryPoint.idempotency_key == message.message_id
        ))
        if existing:
            add_alarm(
                session, source_type="data_quality", source_id=existing.id,
                related_object_type="device", related_object_id=existing.device_id,
                severity="warning", condition={"reason": "duplicate_message",
                                               "message_id": message.message_id},
            )
            results.append({"message_id": message.message_id, "status": "duplicate"})
            continue
        device = session.get(Device, message.device_id)
        point = session.scalar(select(SensorPoint).where(
            SensorPoint.id == message.point_id,
        ).with_for_update())
        if device is None or not device.is_active or point is None or not point.is_active or point.device_id != message.device_id:
            add_alarm(
                session, source_type="data_quality", source_id=None,
                related_object_type="device", related_object_id=message.device_id,
                severity="warning", condition={"reason": "unknown_device_or_point",
                                               "point_id": str(message.point_id)},
            )
            results.append({"message_id": message.message_id, "status": "rejected"})
            continue
        time_issue = check_message_time(message.event_time)
        if time_issue or message.quality.lower() not in {"good", "valid", "ok"}:
            add_alarm(
                session, source_type="data_quality", source_id=point.id,
                related_object_type="device", related_object_id=device.id, severity="warning",
                condition={"reason": time_issue or "quality_bad", "message_id": message.message_id},
            )
            results.append({"message_id": message.message_id, "status": "rejected"})
            continue
        if message.unit != point.unit:
            add_alarm(
                session, source_type="data_quality", source_id=point.id,
                related_object_type="device", related_object_id=device.id, severity="warning",
                condition={"reason": "unit_mismatch", "expected": point.unit, "received": message.unit},
            )
            results.append({"message_id": message.message_id, "status": "rejected"})
            continue
        telemetry = TelemetryPoint(
            message_id=message.message_id, device_id=device.id, point_id=point.id,
            event_time=message.event_time.astimezone(timezone.utc), value=message.value, unit=message.unit,
            quality=message.quality, source=message.source, source_id=message.source_id,
            idempotency_key=message.message_id,
        )
        try:
            with session.begin_nested():
                session.add(telemetry)
                session.flush()
        except IntegrityError:
            if session.scalar(select(TelemetryPoint.id).where(
                TelemetryPoint.idempotency_key == message.message_id,
            )) is None:
                raise
            results.append({"message_id": message.message_id, "status": "duplicate"})
            continue
        evaluate_telemetry(
            session, device=device, point=point, value=message.value, event_time=telemetry.event_time
        )
        results.append({"message_id": message.message_id, "status": "accepted"})
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="测点报文幂等键冲突") from exc
    return {"received": len(results), "results": results}


@router.post("/events", status_code=202)
def ingest_event(
    message: EventMessage, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
) -> dict[str, str]:
    if session.scalar(select(Event.id).where(Event.idempotency_key == message.idempotency_key)):
        add_alarm(
            session, source_type="data_quality", source_id=None,
            related_object_type="device", related_object_id=message.device_id,
            severity="warning", condition={"reason": "duplicate_event",
                                           "idempotency_key": message.idempotency_key},
        )
        session.commit()
        return {"status": "duplicate", "event_id": message.event_id}
    references = [
        (Device, message.device_id, "设备"),
        (CoalBatch, message.batch_id, "来煤批次"),
        (SamplingTask, message.task_id, "采样任务"),
        (Sample, message.sample_id, "样品"),
    ]
    for model, identifier, label in references:
        if identifier is not None and session.get(model, identifier) is None:
            raise HTTPException(status_code=404, detail=f"{label}不存在")
    time_issue = check_message_time(message.occurred_at)
    if time_issue:
        add_alarm(
            session, source_type="data_quality", source_id=None,
            related_object_type="device", related_object_id=message.device_id,
            severity="warning", condition={"reason": time_issue, "event_id": message.event_id},
        )
        session.commit()
        return {"status": "rejected", "event_id": message.event_id}
    event = Event(
        event_id=message.event_id, event_type=message.event_type,
        object_type="device" if message.device_id else None, object_id=message.device_id,
        device_id=message.device_id, batch_id=message.batch_id, task_id=message.task_id,
        sample_id=message.sample_id, occurred_at=message.occurred_at.astimezone(timezone.utc),
        source_id=message.source_id, idempotency_key=message.idempotency_key,
        payload=message.payload,
    )
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
    except IntegrityError as exc:
        if session.scalar(select(Event.id).where(Event.idempotency_key == message.idempotency_key)):
            return {"status": "duplicate", "event_id": message.event_id}
        raise HTTPException(409, "事件编号已存在") from exc
    evaluate_event_rules(session, event)
    session.commit()
    return {"status": "accepted", "event_id": event.event_id}
