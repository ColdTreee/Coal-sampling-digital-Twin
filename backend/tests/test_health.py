from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import main


def test_health_reports_database_ready(monkeypatch) -> None:
    monkeypatch.setattr(main, "check_database", lambda: None)

    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response.headers["x-request-id"]


def test_health_reports_database_unavailable(monkeypatch) -> None:
    def fail_check() -> None:
        raise OperationalError("SELECT 1", {}, RuntimeError("database unavailable"))

    monkeypatch.setattr(main, "check_database", fail_check)

    response = TestClient(main.app).get("/health")

    assert response.status_code == 503
    assert response.json()["code"] == "http_error"
    assert response.json()["request_id"]
