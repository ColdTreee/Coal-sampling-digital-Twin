import argparse
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx


def _post(client: httpx.Client, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def _setup(client: httpx.Client, suffix: str) -> tuple[dict, dict, dict, dict]:
    device = _post(client, "/api/v1/master-data/devices", {
        "device_code": f"SIM-{suffix}", "name": "模拟振动监测设备", "device_type": "sampler",
        "location": "取样间", "twin_object_key": f"sim-{suffix}",
    })
    point = _post(client, "/api/v1/master-data/sensor-points", {
        "point_code": f"VIB-{suffix}", "device_id": device["id"], "metric": "vibration",
        "unit": "mm/s", "range_min": 0, "range_max": 50, "threshold_max": 10,
    })
    batch = _post(client, "/api/v1/batches", {
        "batch_code": f"B-{suffix}", "source": "模拟煤场", "transport_mode": "belt",
    })
    task = _post(client, "/api/v1/sampling-tasks", {
        "task_code": f"T-{suffix}", "batch_id": batch["id"], "strategy_version": "demo-v1",
    })
    sample = _post(client, "/api/v1/samples", {
        "sample_code": f"S-{suffix}", "task_id": task["id"],
        "sample_type": "原煤样", "current_location": "集样器",
    })
    return device, point, batch, {"task": task, "sample": sample}


def run_scenario(name: str, base_url: str = "http://localhost:8000", *, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + uuid4().hex[:4]
    with httpx.Client(base_url=base_url, timeout=10, headers=headers) as client:
        device, point, batch, chain = _setup(client, suffix)
        if name == "normal":
            now = datetime.now(timezone.utc)
            current = {
                "message_id": f"M-{suffix}", "device_id": device["id"], "point_id": point["id"],
                "event_time": now.isoformat(), "value": 4.2,
                "unit": "mm/s", "quality": "good", "source": "simulator",
            }
            _post(client, "/api/v1/ingestion/telemetry", current)
            pending = {**current, "message_id": f"M-REPLAY-{suffix}",
                       "event_time": (now - timedelta(seconds=2)).isoformat()}
            _post(client, "/api/v1/ingestion/telemetry", {"messages": [pending, pending]})
            task_path = f"/api/v1/sampling-tasks/{chain['task']['id']}/status"
            sample_path = f"/api/v1/samples/{chain['sample']['id']}/status"
            client.patch(task_path, json={"status": "running"}).raise_for_status()
            for status in ("collected", "prepared", "sealed"):
                client.patch(sample_path, json={"status": status}).raise_for_status()
            client.patch(task_path, json={"status": "completed"}).raise_for_status()
        elif name == "threshold_alarm":
            _post(client, "/api/v1/master-data/alarm-rules", {
                "rule_code": f"R-{suffix}", "name": "模拟振动超限",
                "condition": {"kind": "threshold", "point_code": point["point_code"], "threshold": 10},
                "severity": "critical",
            })
            _post(client, "/api/v1/ingestion/telemetry", {
                "message_id": f"M-{suffix}", "device_id": device["id"], "point_id": point["id"],
                "event_time": datetime.now(timezone.utc).isoformat(), "value": 15.5,
                "unit": "mm/s", "quality": "good", "source": "simulator",
            })
            _post(client, "/api/v1/ingestion/events", {
                "event_id": f"E-{suffix}", "event_type": "device.threshold_simulated",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "device_id": device["id"], "batch_id": batch["id"],
                "task_id": chain["task"]["id"], "sample_id": chain["sample"]["id"],
                "payload": {"point_code": point["point_code"], "value": 15.5},
                "idempotency_key": f"event:{suffix}",
            })
            alarm = next(item for item in client.get("/api/v1/alarms").json()["items"]
                         if item["source_type"] == "telemetry"
                         and item["trigger_condition"].get("point_code") == point["point_code"])
            _post(client, f"/api/v1/alarms/{alarm['id']}/actions", {
                "action": "confirm", "note": "演示场景已检查设备状态",
            })
            _post(client, f"/api/v1/alarms/{alarm['id']}/actions", {
                "action": "close", "note": "演示场景完成处置",
            })
        else:
            _post(client, "/api/v1/master-data/alarm-rules", {
                "rule_code": f"R-{suffix}", "name": "样品流转超时",
                "condition": {"kind": "process_timeout", "max_seconds": 60,
                              "event_type": "sample.waiting", "sample_id": chain["sample"]["id"]},
                "severity": "warning",
            })
            _post(client, "/api/v1/ingestion/events", {
                "event_id": f"E-{suffix}", "event_type": "sample.waiting",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "batch_id": batch["id"], "task_id": chain["task"]["id"],
                "sample_id": chain["sample"]["id"],
                "payload": {"duration_seconds": 61, "process_node": "sample_transfer"},
                "idempotency_key": f"event:{suffix}",
            })
        trace = client.get(f"/api/v1/batches/{batch['id']}/trace")
        trace.raise_for_status()
        return {"scenario": name, "batch_code": batch["batch_code"], "trace": trace.json()}


def main(default_scenario: str | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token")
    if default_scenario is None:
        parser.add_argument("scenario", choices=["normal", "threshold_alarm", "timeout_trace"])
    args = parser.parse_args()
    scenario = default_scenario or args.scenario
    result = run_scenario(scenario, args.base_url, token=args.token)
    print(f"场景 {scenario} 已完成，批次编号 {result['batch_code']}")


if __name__ == "__main__":
    main()
