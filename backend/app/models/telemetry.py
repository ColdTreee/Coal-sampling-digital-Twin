from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TelemetryPoint(Base):
    __tablename__ = "telemetry_points"
    __table_args__ = (
        Index("ix_telemetry_device_event_time", "device_id", "event_time"),
        Index("ix_telemetry_point_event_time", "point_id", "event_time"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[str] = mapped_column(String(120))
    device_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("devices.id"), index=True)
    point_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sensor_points.id"), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    quality: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[str | None] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
