import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.security import AuthenticatedUser, require_roles
from app.models import Alarm, CoalBatch, Device, Sample, SamplingTask, SensorPoint, TelemetryPoint

router = APIRouter(prefix="/twin", tags=["twin"])
listeners: set[asyncio.Queue] = set()


def notify_state_changed() -> None:
    for queue in listeners:
        if queue.empty():
            queue.put_nowait(None)


@router.websocket("/updates")
async def updates(socket: WebSocket, token: str | None = None):
    if token is None:
        await socket.close(code=1008)
        return
    from app.auth.security import decode_token
    try:
        decode_token(token)
    except HTTPException:
        await socket.close(code=1008)
        return
    await socket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    listeners.add(queue)
    receive = asyncio.create_task(socket.receive())
    try:
        while True:
            pending_update = asyncio.create_task(queue.get())
            try:
                ready, _ = await asyncio.wait(
                    (receive, pending_update), return_when=asyncio.FIRST_COMPLETED,
                )
                if receive in ready:
                    if receive.result()["type"] == "websocket.disconnect":
                        break
                    receive = asyncio.create_task(socket.receive())
                if pending_update in ready:
                    await socket.send_json({"type": "state_changed"})
            finally:
                pending_update.cancel()
                await asyncio.gather(pending_update, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    finally:
        listeners.discard(queue)
        receive.cancel()
        await asyncio.gather(receive, return_exceptions=True)


@router.get("/state")
def state(session: Session = Depends(get_db)):
    batch = session.scalar(select(CoalBatch).where(CoalBatch.is_void.is_(False)).order_by(
        CoalBatch.created_at.desc(), CoalBatch.id.desc(),
    ).limit(1))
    devices = session.scalars(select(Device).where(Device.is_active.is_(True)).order_by(Device.device_code))
    alarm_ids = set(session.scalars(select(Alarm.related_object_id).where(
        Alarm.related_object_type == "device", Alarm.status != "closed",
    )))
    samples = []
    if batch:
        samples = list(session.scalars(select(Sample).join(SamplingTask, Sample.task_id == SamplingTask.id).where(
            SamplingTask.batch_id == batch.id, SamplingTask.is_void.is_(False), Sample.is_void.is_(False),
        ).order_by(Sample.sample_code)))
    return {
        "devices": [{
            "id": device.id,
            "device_code": device.device_code,
            "name": device.name,
            "twin_object_key": device.twin_object_key,
            "status": device.status,
            "alarm": device.id in alarm_ids,
        } for device in devices],
        "current_batch": {"id": batch.id, "batch_code": batch.batch_code} if batch else None,
        "samples": [{"sample_code": item.sample_code, "location": item.current_location,
                     "status": item.status} for item in samples],
        "open_alarms": session.scalar(select(func.count(Alarm.id)).where(Alarm.status != "closed")),
    }


@router.get("/trends")
def trends(
    point_id: UUID, limit: int = Query(120, ge=1, le=1000),
    session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator", "readonly")),
):
    point = session.get(SensorPoint, point_id)
    if point is None or not point.is_active:
        raise HTTPException(404, "测点不存在")
    rows = list(session.scalars(select(TelemetryPoint).where(
        TelemetryPoint.point_id == point_id,
    ).order_by(TelemetryPoint.event_time.desc(), TelemetryPoint.id.desc()).limit(limit)))
    return {
        "point_code": point.point_code,
        "unit": point.unit,
        "threshold_max": point.threshold_max,
        "items": [{"time": row.event_time.isoformat() if row.event_time.tzinfo
                   else row.event_time.isoformat() + "Z", "value": row.value} for row in reversed(rows)],
    }
