from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.alarms.service import evaluate_rule
from app.models import AlarmRule


def _device_and_point(client):
    device = client.post(
        "/api/v1/master-data/devices",
        json={"device_code": "DEV-INGEST", "name": "振动监测点", "device_type": "sensor"},
    ).json()
    point = client.post(
        "/api/v1/master-data/sensor-points",
        json={
            "point_code": "VIB-01", "device_id": device["id"], "metric": "vibration",
            "unit": "mm/s", "range_min": 0, "range_max": 20, "threshold_max": 10,
        },
    ).json()
    return device, point


def test_telemetry_is_idempotent_and_threshold_alarm_can_be_closed(client) -> None:
    device, point = _device_and_point(client)
    rule = client.post(
        "/api/v1/master-data/alarm-rules",
        json={
            "rule_code": "VIB-HIGH", "name": "振动超限",
            "condition": {"kind": "threshold", "point_code": "VIB-01", "threshold": 10},
            "severity": "critical",
        },
    )
    assert rule.status_code == 201
    message = {
        "message_id": "MSG-001", "device_id": device["id"], "point_id": point["id"],
        "event_time": datetime.now(timezone.utc).isoformat(), "value": 12.5,
        "unit": "mm/s", "quality": "good", "source": "simulator",
    }
    accepted = client.post("/api/v1/ingestion/telemetry", json=message)
    repeated = client.post("/api/v1/ingestion/telemetry", json=message)
    assert accepted.json()["results"][0]["status"] == "accepted"
    assert repeated.json()["results"][0]["status"] == "duplicate"
    alarms = client.get("/api/v1/alarms?severity=critical").json()["items"]
    assert len(alarms) == 1
    alarm_id = alarms[0]["id"]
    confirmed = client.post(f"/api/v1/alarms/{alarm_id}/actions", json={"action": "confirm", "note": "已核查"})
    closed = client.post(f"/api/v1/alarms/{alarm_id}/actions", json={"action": "close", "note": "恢复正常"})
    assert confirmed.json()["status"] == "acknowledged"
    assert closed.json()["status"] == "closed"


def test_invalid_device_or_point_is_rejected_and_raises_quality_alarm(client) -> None:
    response = client.post(
        "/api/v1/ingestion/telemetry",
        json={
            "message_id": "MSG-UNKNOWN", "device_id": str(uuid4()), "point_id": str(uuid4()),
            "event_time": datetime.now(timezone.utc).isoformat(), "value": 1,
            "unit": "mm/s", "quality": "good", "source": "simulator",
        },
    )
    assert response.json()["results"][0]["status"] == "rejected"
    alarms = client.get("/api/v1/alarms").json()["items"]
    assert alarms[0]["trigger_condition"]["reason"] == "unknown_device_or_point"


def test_rule_evaluator_covers_configured_rule_kinds() -> None:
    contexts = {
        "threshold": {"value": 5, "threshold": 4},
        "process_timeout": {"duration_seconds": 11},
        "missing_action": {"expected_action_missing": True},
        "state_inconsistency": {"state_consistent": False},
        "data_quality": {"quality_issue": "unknown_point"},
    }
    for kind, context in contexts.items():
        rule = AlarmRule(
            rule_code=kind, name=kind,
            condition={"kind": kind, "threshold": 4, "max_seconds": 10},
            severity="warning",
        )
        assert evaluate_rule(rule, context)


def test_duration_requires_a_continuous_window_and_rejects_naive_time(client) -> None:
    device, point = _device_and_point(client)
    assert client.post("/api/v1/master-data/alarm-rules", json={
        "rule_code": "DURATION", "name": "持续超阈值", "severity": "critical",
        "condition": {"kind": "threshold", "threshold": 10}, "duration_seconds": 3,
    }).status_code == 201
    start = datetime.now(timezone.utc) - timedelta(seconds=10)
    message = {"device_id": device["id"], "point_id": point["id"],
               "value": 12, "unit": "mm/s", "quality": "good", "source": "simulator"}
    def send(index, second, value):
        return client.post("/api/v1/ingestion/telemetry", json={
            **message, "message_id": str(index), "value": value,
            "event_time": (start + timedelta(seconds=second)).isoformat(),
        })

    assert client.post("/api/v1/ingestion/telemetry", json={
        **message, "message_id": "naive", "event_time": start.replace(tzinfo=None).isoformat(),
    }).status_code == 422
    for index, second, value in [(1, 0, 12), (2, 1, 7), (3, 2, 12), (4, 4, 12)]:
        assert send(index, second, value).json()["results"][0]["status"] == "accepted"
    assert client.get("/api/v1/alarms?severity=critical").json()["items"] == []
    assert send(5, 6, 12).status_code == 200
    assert send(6, 7, 12).status_code == 200
    assert len(client.get("/api/v1/alarms?severity=critical").json()["items"]) == 1
