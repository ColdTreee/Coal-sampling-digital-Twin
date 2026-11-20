from uuid import uuid4


def test_batch_task_sample_events_are_returned_in_trace(client) -> None:
    batch_response = client.post(
        "/api/v1/batches",
        json={"batch_code": "BATCH-001", "source": "北区煤场"},
    )
    assert batch_response.status_code == 201
    batch = batch_response.json()

    task_response = client.post(
        "/api/v1/sampling-tasks",
        json={"task_code": "TASK-001", "batch_id": batch["id"]},
    )
    assert task_response.status_code == 201
    task = task_response.json()

    sample_response = client.post(
        "/api/v1/samples",
        json={"sample_code": "SAMPLE-001", "task_id": task["id"], "sample_type": "原煤样"},
    )
    assert sample_response.status_code == 201

    trace_response = client.get(f"/api/v1/batches/{batch['id']}/trace")
    assert trace_response.status_code == 200
    trace = trace_response.json()
    assert trace["batch"]["batch_code"] == "BATCH-001"
    assert [item["task_code"] for item in trace["tasks"]] == ["TASK-001"]
    assert [item["sample_code"] for item in trace["samples"]] == ["SAMPLE-001"]
    assert [item["event_type"] for item in trace["events"]] == [
        "batch.created",
        "sampling_task.created",
        "sample.created",
    ]
    assert trace["missing_links"] == []


def test_task_requires_existing_batch(client) -> None:
    response = client.post(
        "/api/v1/sampling-tasks",
        json={"task_code": "TASK-MISSING", "batch_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "http_error"
    assert response.json()["request_id"]


def test_duplicate_batch_code_returns_conflict(client) -> None:
    first = client.post("/api/v1/batches", json={"batch_code": "BATCH-DUPLICATE"})
    duplicate = client.post("/api/v1/batches", json={"batch_code": "BATCH-DUPLICATE"})

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "http_error"


def test_sample_requires_each_status_step(client) -> None:
    batch = client.post("/api/v1/batches", json={"batch_code": "LIFE"}).json()
    task = client.post("/api/v1/sampling-tasks", json={
        "task_code": "LIFE-T", "batch_id": batch["id"],
    }).json()
    sample = client.post("/api/v1/samples", json={
        "sample_code": "LIFE-S", "task_id": task["id"], "sample_type": "原煤样",
    }).json()
    path = f"/api/v1/samples/{sample['id']}/status"
    assert client.patch(path, json={"status": "sealed"}).status_code == 409
    for status in ("collected", "prepared", "sealed"):
        response = client.patch(path, json={"status": status})
        assert response.status_code == 200
    assert response.json()["is_sealed"]
    trace = client.get(f"/api/v1/batches/{batch['id']}/trace").json()
    assert trace["events"][-1]["event_type"] == "sample.sealed"


def test_empty_batch_trace_reports_missing_links(client) -> None:
    batch_response = client.post("/api/v1/batches", json={"batch_code": "BATCH-EMPTY"})
    batch_id = batch_response.json()["id"]

    trace = client.get(f"/api/v1/batches/{batch_id}/trace").json()

    assert trace["missing_links"] == ["尚无采样任务"]
