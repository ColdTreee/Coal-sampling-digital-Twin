from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alarm, AlarmRule, Device, Event, SensorPoint, TelemetryPoint


def evaluate_rule(rule: AlarmRule, context: dict[str, Any]) -> bool:
    condition = rule.condition
    kind = condition.get("kind")
    if kind == "threshold":
        value = context.get("value")
        threshold = condition.get("threshold")
        if value is None or threshold is None:
            return False
        return value > threshold if condition.get("operator", "gt") == "gt" else value < threshold
    if kind == "process_timeout":
        duration = context.get("duration_seconds", 0)
        return isinstance(duration, (int, float)) and duration > condition.get("max_seconds", float("inf"))
    if kind == "missing_action":
        return context.get("expected_action_missing", False) is True
    if kind == "state_inconsistency":
        return context.get("state_consistent", True) is False
    if kind == "data_quality":
        return bool(context.get("quality_issue"))
    return False


def add_alarm(
    session: Session,
    *,
    source_type: str,
    source_id: UUID | None,
    related_object_type: str | None,
    related_object_id: UUID | None,
    severity: str,
    condition: dict[str, Any],
    rule: AlarmRule | None = None,
) -> Alarm:
    alarm = Alarm(
        rule_id=rule.id if rule else None,
        source_type=source_type,
        source_id=source_id,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        severity=severity,
        trigger_condition=condition,
    )
    session.add(alarm)
    return alarm


def evaluate_telemetry(
    session: Session,
    *,
    device: Device,
    point: SensorPoint,
    value: float,
    event_time: datetime,
) -> list[Alarm]:
    alarms = []
    for bound, reason in ((point.range_min, "below_range"), (point.range_max, "above_range")):
        if bound is None or ((reason == "below_range" and value >= bound)
                             or (reason == "above_range" and value <= bound)):
            continue
        alarms.append(add_alarm(
            session, source_type="data_quality", source_id=point.id,
            related_object_type="device", related_object_id=device.id, severity="warning",
            condition={"reason": reason, "value": value, "bound": bound},
        ))

    rules = session.scalars(select(AlarmRule).where(AlarmRule.is_enabled.is_(True)))
    for rule in rules:
        condition = rule.condition
        if condition.get("kind") != "threshold":
            continue
        if condition.get("point_code") not in (None, point.point_code):
            continue
        operator = condition.get("operator", "gt")
        fallback = point.threshold_min if operator == "lt" else point.threshold_max
        threshold = condition.get("threshold", fallback)
        if threshold is None or not (value < threshold if operator == "lt" else value > threshold):
            continue
        exceeds = TelemetryPoint.value < threshold if operator == "lt" else TelemetryPoint.value > threshold
        duration = max(rule.duration_seconds, 0)
        if duration:
            window_start = event_time - timedelta(seconds=duration)
            reset = session.scalar(select(TelemetryPoint.id).where(
                TelemetryPoint.point_id == point.id,
                TelemetryPoint.event_time > window_start,
                TelemetryPoint.event_time <= event_time,
                ~exceeds,
            ).limit(1))
            boundary_exceeds = session.scalar(select(exceeds).where(
                TelemetryPoint.point_id == point.id,
                TelemetryPoint.event_time <= window_start,
            ).order_by(TelemetryPoint.event_time.desc(), TelemetryPoint.received_at.desc(),
                       TelemetryPoint.id.desc()).limit(1))
            if reset is not None or not boundary_exceeds:
                continue
        if session.scalar(select(Alarm.id).where(
            Alarm.rule_id == rule.id, Alarm.source_id == point.id, Alarm.status != "closed",
        ).limit(1)):
            continue
        alarms.append(add_alarm(
            session, source_type="telemetry", source_id=point.id,
            related_object_type="device", related_object_id=device.id, severity=rule.severity,
            condition={"point_code": point.point_code, "value": value,
                       "operator": operator, "threshold": threshold, "duration_seconds": duration},
            rule=rule,
        ))
    return alarms


def check_message_time(event_time: datetime, now: datetime | None = None) -> str | None:
    now = now or datetime.now(timezone.utc)
    if event_time > now + timedelta(minutes=5):
        return "timestamp_in_future"
    if event_time < now - timedelta(days=1):
        return "timestamp_too_old"
    return None


def evaluate_event_rules(session: Session, event: Event) -> list[Alarm]:
    context = event.payload
    related = next(
        ((name, identifier) for name, identifier in (
            ("sample", event.sample_id),
            ("sampling_task", event.task_id),
            ("batch", event.batch_id),
            ("device", event.device_id),
        ) if identifier is not None),
        (None, None),
    )
    alarms = []
    for rule in session.scalars(select(AlarmRule).where(AlarmRule.is_enabled.is_(True))):
        if rule.condition.get("kind") == "threshold":
            continue
        if rule.condition.get("event_type") not in (None, event.event_type):
            continue
        if rule.condition.get("sample_id") not in (None, str(event.sample_id)):
            continue
        if not evaluate_rule(rule, context):
            continue
        alarms.append(add_alarm(
            session,
            source_type=rule.condition.get("kind", "event"),
            source_id=event.id,
            related_object_type=related[0],
            related_object_id=related[1],
            severity=rule.severity,
            condition={"rule_code": rule.rule_code, **context},
            rule=rule,
        ))
    return alarms
