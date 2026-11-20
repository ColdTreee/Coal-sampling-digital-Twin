import csv
import io


def test_readonly_role_cannot_write_and_bad_token_is_rejected(client) -> None:
    readonly_headers = {
        "Authorization": "Bearer " + client.role_tokens["readonly"],
    }
    denied = client.post(
        "/api/v1/batches",
        json={"batch_code": "READONLY-DENIED"},
        headers=readonly_headers,
    )
    assert denied.status_code == 403
    assert client.get("/api/v1/batches", headers=readonly_headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_report_export_is_utf8_csv_and_is_audited(client) -> None:
    created = client.post("/api/v1/batches", json={"batch_code": "REPORT-001", "source": "北区"})
    assert created.status_code == 201
    response = client.get("/api/v1/reports/trace.csv?batch_id=" + created.json()["id"])
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert rows[1][0] == "批次"
    assert rows[1][1] == "REPORT-001"
    actions = client.get("/api/v1/audit/logs?action=report.trace_csv").json()["items"]
    assert len(actions) == 1


def test_admin_can_create_account_and_login(client) -> None:
    response = client.post("/api/v1/auth/users", json={
        "username": "new-operator",
        "password": "unique-long-password",
        "role": "operator",
    })
    assert response.status_code == 201
    login = client.post("/api/v1/auth/login", data={
        "username": "new-operator",
        "password": "unique-long-password",
    })
    assert login.status_code == 200
    assert login.json()["roles"] == ["operator"]
