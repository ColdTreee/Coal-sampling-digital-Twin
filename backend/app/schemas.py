from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat


class BatchCreate(BaseModel):
    batch_code: str = Field(min_length=1, max_length=80)
    source: str | None = Field(default=None, max_length=160)
    transport_mode: str | None = Field(default=None, max_length=80)
    arrived_at: datetime | None = None


class BatchRead(BatchCreate):
    id: UUID
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    task_code: str = Field(min_length=1, max_length=80)
    batch_id: UUID
    planned_at: datetime | None = None
    strategy_version: str | None = Field(default=None, max_length=80)


class TaskRead(TaskCreate):
    id: UUID
    status: str
    model_config = ConfigDict(from_attributes=True)


class SampleCreate(BaseModel):
    sample_code: str = Field(min_length=1, max_length=80)
    task_id: UUID
    sample_type: str = Field(min_length=1, max_length=80)
    current_location: str | None = Field(default=None, max_length=160)


class SampleRead(SampleCreate):
    id: UUID
    status: str
    is_sealed: bool
    model_config = ConfigDict(from_attributes=True)


class DeviceCreate(BaseModel):
    device_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    device_type: str = Field(min_length=1, max_length=80)
    location: str | None = Field(default=None, max_length=255)
    twin_object_key: str | None = Field(default=None, max_length=120)


class DeviceRead(DeviceCreate):
    id: UUID
    status: str
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class SensorPointCreate(BaseModel):
    point_code: str = Field(min_length=1, max_length=80)
    device_id: UUID
    metric: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=32)
    range_min: float | None = None
    range_max: float | None = None
    threshold_min: float | None = None
    threshold_max: float | None = None


class TelemetryMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=120)
    device_id: UUID
    point_id: UUID
    event_time: AwareDatetime
    value: FiniteFloat
    unit: str = Field(min_length=1, max_length=32)
    quality: str = Field(min_length=1, max_length=32)
    source: str = Field(min_length=1, max_length=80)
    source_id: str | None = Field(default=None, max_length=120)


class TelemetryBatch(BaseModel):
    messages: list[TelemetryMessage] = Field(min_length=1, max_length=500)


class EventMessage(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=100)
    occurred_at: AwareDatetime
    device_id: UUID | None = None
    batch_id: UUID | None = None
    task_id: UUID | None = None
    sample_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=160)
    source_id: str | None = Field(default=None, max_length=120)


class AlarmActionCreate(BaseModel):
    action: str = Field(pattern="^(confirm|note|close)$")
    note: str | None = Field(default=None, max_length=2000)


class AlarmRuleCreate(BaseModel):
    rule_code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    condition: dict[str, Any]
    duration_seconds: float = Field(default=0, ge=0)
    severity: str = Field(pattern="^(info|warning|critical)$")


class StatusChange(BaseModel):
    status: str = Field(min_length=1, max_length=40)


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=12, max_length=256)
    role: str = Field(pattern="^(administrator|operator|readonly)$")
