from sqlalchemy import DateTime, Uuid
from app.models import Base

def test_core_entities_are_registered() -> None:
    expected = {"users", "roles", "user_roles", "devices", "sensor_points", "coal_batches",
                "sampling_tasks", "samples", "telemetry_points", "events", "alarm_rules",
                "alarms", "alarm_actions", "audit_logs"}
    assert expected <= set(Base.metadata.tables)

def test_primary_keys_use_uuid_and_timestamps_are_timezone_aware() -> None:
    for table in Base.metadata.tables.values():
        assert isinstance(next(iter(table.primary_key.columns)).type, Uuid)
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone
