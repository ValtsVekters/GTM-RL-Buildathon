import json

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def lines(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_demo_run_streams_agent_events_then_the_result():
    response = client.post("/research", json={"product": main.sample_product(), "max_leads": 15, "mode": "demo"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    out = lines(response)
    assert all(line["type"] == "event" for line in out[:-1])
    assert out[0]["event"]["agent"] == "ICP strategist"
    assert out[-1]["type"] == "result"
    leads = out[-1]["result"]["leads"]
    assert [lead["company"] for lead in leads][:2] == ["Pulse Arena Esports", "IronCore Gyms"]
    assert out[-1]["result"]["quota_left"]["hunter"] < 50


def test_rejects_a_too_short_product_or_too_many_leads():
    assert client.post("/research", json={"product": "mints"}).status_code == 422
    assert client.post("/research", json={"product": main.sample_product(), "max_leads": 99}).status_code == 422
    assert client.post("/research", json={"product": main.sample_product(), "mode": "paid"}).status_code == 422


def test_refuses_a_second_run_while_one_is_in_progress():
    assert main._run_lock.acquire(blocking=False)
    try:
        response = client.post("/research", json={"product": main.sample_product()})
        assert response.status_code == 409
        assert "already in progress" in response.json()["detail"]
    finally:
        main._run_lock.release()


def test_failure_sends_a_fixed_message_not_the_provider_error(monkeypatch):
    class Boom:
        def run(self, product):
            raise main.LLMUnavailable("parasail: HTTP 401: {'account': 'acct_secret_123'}")

    monkeypatch.setattr(main, "build_crew", lambda *a, **k: Boom())
    out = lines(client.post("/research", json={"product": main.sample_product()}))
    assert out == [{"type": "error", "message": "No model is available. Run check_keys.py in worker/ "
                                                "to see which API keys are missing or rejected."}]
    assert "acct_secret_123" not in json.dumps(out)


def test_sample_returns_the_demo_product():
    assert "energy mints" in client.get("/sample").json()["product"].lower()
