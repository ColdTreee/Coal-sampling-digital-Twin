from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    device_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    device_type: Mapped[str] = mapped_column(String(80))
    location: Mapped[str | None] = mapped_column(String(255))
    twin_object_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="unknown", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SensorPoint(Base):
    __tablename__ = "sensor_points"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    point_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    device_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("devices.id"), index=True)
    metric: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(32))
    range_min: Mapped[float | None] = mapped_column(Float)
    range_max: Mapped[float | None] = mapped_column(Float)
    threshold_min: Mapped[float | None] = mapped_column(Float)
    threshold_max: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
