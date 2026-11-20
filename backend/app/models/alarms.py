from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AlarmRule(Base):
    __tablename__ = "alarm_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    rule_code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    condition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    severity: Mapped[str] = mapped_column(String(32))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)


class Alarm(Base):
    __tablename__ = "alarms"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    rule_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("alarm_rules.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(80))
    source_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    related_object_type: Mapped[str | None] = mapped_column(String(80))
    related_object_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    severity: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    trigger_condition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    first_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlarmAction(Base):
    __tablename__ = "alarm_actions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    alarm_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("alarms.id"), index=True)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    action_type: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
