from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CoalBatch(Base):
    __tablename__ = "coal_batches"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    batch_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    source: Mapped[str | None] = mapped_column(String(160))
    transport_mode: Mapped[str | None] = mapped_column(String(80))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="registered", nullable=False)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SamplingTask(Base):
    __tablename__ = "sampling_tasks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    task_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    batch_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("coal_batches.id"), index=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="planned", nullable=False)
    strategy_version: Mapped[str | None] = mapped_column(String(80))
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    sample_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sampling_tasks.id"), index=True)
    sample_type: Mapped[str] = mapped_column(String(80))
    current_location: Mapped[str | None] = mapped_column(String(160))
    is_sealed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="created", nullable=False)
    is_void: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
