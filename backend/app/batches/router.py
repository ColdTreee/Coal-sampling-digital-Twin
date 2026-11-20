from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.auth.security import AuthenticatedUser, require_roles
from app.events.service import record_event
from app.models import Alarm, AuditLog, CoalBatch, Event, Sample, SamplingTask
from app.schemas import BatchCreate, BatchRead, SampleCreate, SampleRead, StatusChange, TaskCreate, TaskRead

router = APIRouter(tags=["batches"])

TASK_TRANSITIONS = {
    "planned": {"running", "cancelled"},
    "running": {"completed", "cancelled"},
}
SAMPLE_LOCATIONS = {
    "collected": "集样器",
    "prepared": "制样间",
    "sealed": "样品库",
}
SAMPLE_TRANSITIONS = {
    "created": {"collected", "void"},
    "collected": {"prepared", "void"},
    "prepared": {"sealed", "void"},
    "sealed": {"void"},
}


@router.post("/batches", response_model=BatchRead, status_code=201)
def create_batch(
    body: BatchCreate, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
) -> CoalBatch:
    batch = CoalBatch(**body.model_dump())
    session.add(batch)
    session.add(AuditLog(actor_id=identity.user.id, action="batch.create",
                         target_type="coal_batch", outcome="success",
                         change_summary={"batch_code": body.batch_code}))
    try:
        session.flush()
        record_event(
            session,
            event_type="batch.created",
            object_type="batch",
            object_id=batch.id,
            batch_id=batch.id,
            payload={"batch_code": batch.batch_code},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="批次编号已存在") from exc
    session.refresh(batch)
    return batch


@router.get("/batches", response_model=list[BatchRead])
def list_batches(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = None,
    session: Session = Depends(get_db),
) -> list[CoalBatch]:
    query = select(CoalBatch).where(CoalBatch.is_void.is_(False))
    if status:
        query = query.where(CoalBatch.status == status)
    return list(session.scalars(query.order_by(CoalBatch.created_at.desc()).offset(offset).limit(limit)))


@router.post("/sampling-tasks", response_model=TaskRead, status_code=201)
def create_task(
    body: TaskCreate, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
) -> SamplingTask:
    batch = session.get(CoalBatch, body.batch_id)
    if batch is None or batch.is_void:
        raise HTTPException(status_code=404, detail="来煤批次不存在或已作废")
    task = SamplingTask(**body.model_dump())
    session.add(task)
    session.add(AuditLog(actor_id=identity.user.id, action="sampling_task.create",
                         target_type="sampling_task", outcome="success",
                         change_summary={"task_code": body.task_code}))
    try:
        session.flush()
        record_event(
            session,
            event_type="sampling_task.created",
            object_type="sampling_task",
            object_id=task.id,
            batch_id=batch.id,
            task_id=task.id,
            payload={"task_code": task.task_code, "status": task.status},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="任务编号已存在") from exc
    session.refresh(task)
    return task


@router.post("/samples", response_model=SampleRead, status_code=201)
def create_sample(
    body: SampleCreate, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
) -> Sample:
    task = session.get(SamplingTask, body.task_id)
    if task is None or task.is_void:
        raise HTTPException(status_code=404, detail="采样任务不存在或已作废")
    sample = Sample(**body.model_dump())
    session.add(sample)
    session.add(AuditLog(actor_id=identity.user.id, action="sample.create",
                         target_type="sample", outcome="success",
                         change_summary={"sample_code": body.sample_code}))
    try:
        session.flush()
        record_event(
            session,
            event_type="sample.created",
            object_type="sample",
            object_id=sample.id,
            batch_id=task.batch_id,
            task_id=task.id,
            sample_id=sample.id,
            payload={"sample_code": sample.sample_code, "status": sample.status},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="样品编号已存在") from exc
    session.refresh(sample)
    return sample


@router.patch("/sampling-tasks/{task_id}/status", response_model=TaskRead)
def set_task_status(
    task_id: UUID, body: StatusChange, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
):
    task = session.scalar(select(SamplingTask).where(SamplingTask.id == task_id).with_for_update())
    if task is None or task.is_void:
        raise HTTPException(404, "采样任务不存在")
    previous = task.status
    if body.status not in TASK_TRANSITIONS.get(previous, set()):
        raise HTTPException(409, "不允许的任务状态转换")
    now = datetime.now(timezone.utc)
    task.status = body.status
    if body.status == "running":
        task.actual_start_at = now
    elif task.actual_start_at:
        task.actual_end_at = now
    record_event(
        session, event_type=f"sampling_task.{body.status}", object_type="sampling_task",
        object_id=task.id, batch_id=task.batch_id, task_id=task.id, occurred_at=now,
        payload={"previous_status": previous, "status": body.status},
    )
    session.add(AuditLog(actor_id=identity.user.id, action="sampling_task.status",
                         target_type="sampling_task", target_id=str(task.id), outcome="success",
                         change_summary={"from": previous, "to": body.status}))
    session.commit()
    return task


@router.patch("/samples/{sample_id}/status", response_model=SampleRead)
def set_sample_status(
    sample_id: UUID, body: StatusChange, session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
):
    sample = session.scalar(select(Sample).where(Sample.id == sample_id).with_for_update())
    if sample is None or sample.is_void:
        raise HTTPException(404, "样品不存在")
    previous = sample.status
    if body.status not in SAMPLE_TRANSITIONS.get(previous, set()):
        raise HTTPException(409, "不允许的样品状态转换")
    task = session.get(SamplingTask, sample.task_id)
    sample.status = body.status
    sample.is_void = body.status == "void"
    sample.current_location = SAMPLE_LOCATIONS.get(body.status, sample.current_location)
    if body.status == "sealed":
        sample.is_sealed = True
    record_event(
        session, event_type=f"sample.{body.status}", object_type="sample", object_id=sample.id,
        batch_id=task.batch_id, task_id=task.id, sample_id=sample.id,
        payload={"previous_status": previous, "status": body.status,
                 "location": sample.current_location},
    )
    session.add(AuditLog(actor_id=identity.user.id, action="sample.status",
                         target_type="sample", target_id=str(sample.id), outcome="success",
                         change_summary={"from": previous, "to": body.status}))
    session.commit()
    return sample


@router.get("/batches/{batch_id}/trace")
def get_batch_trace(batch_id: UUID, session: Session = Depends(get_db)) -> dict:
    batch = session.scalar(select(CoalBatch).where(CoalBatch.id == batch_id, CoalBatch.is_void.is_(False)))
    if batch is None:
        raise HTTPException(status_code=404, detail="来煤批次不存在")
    tasks = list(session.scalars(select(SamplingTask).where(
        SamplingTask.batch_id == batch.id, SamplingTask.is_void.is_(False)
    )))
    task_ids = [task.id for task in tasks]
    samples = list(session.scalars(select(Sample).where(
        Sample.task_id.in_(task_ids), Sample.is_void.is_(False)
    ))) if task_ids else []
    sample_ids = [sample.id for sample in samples]
    events_query = select(Event).where(
        (Event.batch_id == batch.id)
        | (Event.task_id.in_(task_ids) if task_ids else Event.id.is_(None))
        | (Event.sample_id.in_(sample_ids) if sample_ids else Event.id.is_(None))
    )
    events = list(session.scalars(events_query.order_by(Event.occurred_at)))
    device_ids = {event.device_id for event in events if event.device_id is not None}
    related_ids = [batch.id, *task_ids, *sample_ids, *device_ids]
    alarms = list(session.scalars(select(Alarm).where(
        Alarm.related_object_id.in_(related_ids)
    ).order_by(Alarm.first_triggered_at, Alarm.id)))
    return {
        "batch": BatchRead.model_validate(batch),
        "tasks": [TaskRead.model_validate(task) for task in tasks],
        "samples": [SampleRead.model_validate(sample) for sample in samples],
        "events": [
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "occurred_at": event.occurred_at,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "device_id": event.device_id,
                "task_id": event.task_id,
                "sample_id": event.sample_id,
                "payload": event.payload,
            }
            for event in events
        ],
        "alarms": [
            {"id": alarm.id, "severity": alarm.severity, "status": alarm.status,
             "first_triggered_at": alarm.first_triggered_at,
             "related_object_id": alarm.related_object_id,
             "related_object_type": alarm.related_object_type,
             "trigger_condition": alarm.trigger_condition}
            for alarm in alarms
        ],
        "missing_links": _missing_links(tasks, samples, events),
    }


def _missing_links(tasks: list[SamplingTask], samples: list[Sample], events: list[Event]) -> list[str]:
    missing = []
    if not tasks:
        missing.append("尚无采样任务")
    tasks_with_samples = {sample.task_id for sample in samples}
    for task in tasks:
        if task.id not in tasks_with_samples:
            missing.append(f"采样任务 {task.task_code} 尚未生成样品")
    if not events:
        missing.append("尚无业务事件")
    return missing
