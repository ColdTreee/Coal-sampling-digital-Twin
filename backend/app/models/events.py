from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_object_time", "object_type", "object_id", "occurred_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    object_type: Mapped[str | None] = mapped_column(String(80))
    object_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    device_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("devices.id"), index=True)
    batch_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("coal_batches.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sampling_tasks.id"), index=True)
    sample_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("samples.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_id: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
