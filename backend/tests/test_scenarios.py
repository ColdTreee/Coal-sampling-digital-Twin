import pytest

from simulator import scenarios


@pytest.mark.parametrize("name", ["normal", "threshold_alarm", "timeout_trace"])
def test_demo_scenario(name, client, monkeypatch):
    class LocalClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return client

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(scenarios.httpx, "Client", LocalClient)
    trace = scenarios.run_scenario(name)["trace"]
    assert not trace["missing_links"]
    if name == "normal":
        assert trace["tasks"][0]["status"] == "completed"
        assert trace["samples"][0]["is_sealed"] is True
    elif name == "timeout_trace":
        assert trace["alarms"][0]["trigger_condition"]["process_node"] == "sample_transfer"
    else:
        alarms = client.get("/api/v1/alarms?severity=critical").json()["items"]
        assert alarms[0]["status"] == "closed"
        assert len(trace["alarms"]) == 1
