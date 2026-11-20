from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.models import Event


def record_event(
    session: Session,
    *,
    event_type: str,
    object_type: str,
    object_id: UUID,
    occurred_at: datetime | None = None,
    batch_id: UUID | None = None,
    task_id: UUID | None = None,
    sample_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> Event:
    event_uuid = uuid4()
    event = Event(
        event_id=str(event_uuid),
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        batch_id=batch_id,
        task_id=task_id,
        sample_id=sample_id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        idempotency_key=f"business:{event_type}:{object_id}",
        payload=payload or {},
    )
    session.add(event)
    return event
