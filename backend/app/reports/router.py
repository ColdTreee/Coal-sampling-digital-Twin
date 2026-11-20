import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import AuthenticatedUser, require_roles
from app.core.database import get_db
from app.models import Alarm, AuditLog, CoalBatch, Event, Sample, SamplingTask

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/trace.csv")
def export_trace_csv(
    batch_id: UUID | None = None,
    offset: int = Query(0, ge=0), limit: int = Query(5000, ge=1, le=10000),
    session: Session = Depends(get_db),
    identity: AuthenticatedUser = Depends(require_roles("administrator", "operator")),
):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["记录类型", "批次编号", "对象编号", "事件类型", "状态/级别", "时间", "详情"])
    query = select(CoalBatch).where(CoalBatch.is_void.is_(False)).order_by(
        CoalBatch.created_at.desc(), CoalBatch.id.desc(),
    )
    if batch_id:
        query = query.where(CoalBatch.id == batch_id)
    for batch in session.scalars(query.offset(offset).limit(limit)):
        writer.writerow(["批次", batch.batch_code, str(batch.id), "", batch.status,
                         batch.arrived_at.isoformat() if batch.arrived_at else "", batch.source or ""])
        tasks = list(session.scalars(select(SamplingTask).where(
            SamplingTask.batch_id == batch.id, SamplingTask.is_void.is_(False),
        )))
        task_ids = [task.id for task in tasks]
        sample_ids = list(session.scalars(select(Sample.id).where(
            Sample.task_id.in_(task_ids),
        ))) if task_ids else []
        for task in tasks:
            writer.writerow(["任务", batch.batch_code, task.task_code, "", task.status,
                             task.actual_start_at.isoformat() if task.actual_start_at else "",
                             task.strategy_version or ""])
            for sample in session.scalars(select(Sample).where(
                Sample.task_id == task.id, Sample.is_void.is_(False),
            )):
                writer.writerow(["样品", batch.batch_code, sample.sample_code, "", sample.status, "",
                                 sample.current_location or ""])
        event_filter = Event.batch_id == batch.id
        if task_ids:
            event_filter = event_filter | Event.task_id.in_(task_ids)
        if sample_ids:
            event_filter = event_filter | Event.sample_id.in_(sample_ids)
        events = list(session.scalars(select(Event).where(event_filter).order_by(
            Event.occurred_at, Event.id,
        )))
        for event in events:
            writer.writerow(["事件", batch.batch_code, event.event_id, event.event_type, "",
                             event.occurred_at.isoformat(), str(event.payload)])
        device_ids = {event.device_id for event in events if event.device_id is not None}
        related_ids = [batch.id, *task_ids, *sample_ids, *device_ids]
        for alarm in session.scalars(select(Alarm).where(
            Alarm.related_object_id.in_(related_ids),
        ).order_by(Alarm.first_triggered_at, Alarm.id)):
            writer.writerow(["告警", batch.batch_code, str(alarm.id), alarm.source_type, alarm.status,
                             alarm.first_triggered_at.isoformat(), str(alarm.trigger_condition)])
    content = "\ufeff" + output.getvalue()
    session.add(AuditLog(actor_id=identity.user.id, action="report.trace_csv", target_type="report",
                         outcome="success",
                         change_summary={"batch_id": str(batch_id) if batch_id else None,
                                         "offset": offset, "limit": limit}))
    session.commit()
    return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="trace-report.csv"'})
