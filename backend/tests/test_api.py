from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)
REFERENCE_SCENARIO = [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12", "district_id": None},
    {"measure_id": "M5", "district_id": "saryarka"},
]


def test_health_and_config_are_available() -> None:
    assert client.get("/api/health").json() == {"status": "ok"}

    config = client.get("/api/config").json()
    assert config["budget"] == 100
    assert len(config["districts"]) == 5
    assert len(config["measures"]) == 14
    assert config["baseline"]["score"] == 52.55768


def test_partial_validation_endpoint() -> None:
    response = client.post("/api/validate", json={"selections": REFERENCE_SCENARIO[:2]})

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["ready"] is False


def test_simulation_endpoint_returns_deterministic_result() -> None:
    response = client.post("/api/simulate", json={"selections": REFERENCE_SCENARIO})

    assert response.status_code == 200
    assert response.json()["score"] == 56.54307
    assert response.json()["total_cost"] == 95


def test_analyze_endpoint_uses_fallback_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/api/analyze", json={"selections": REFERENCE_SCENARIO})

    assert response.status_code == 200
    assert response.json()["score"] == 56.54307
    assert response.json()["explanation"]["source"] == "rules"
    assert response.json()["explanation"]["status"] == "fallback"
    assert response.json()["alternative_scenarios"]
    assert "вариант" in response.json()["explanation"]["recommendations"][0]


def test_invalid_scenario_does_not_receive_a_score() -> None:
    response = client.post("/api/simulate", json={"selections": REFERENCE_SCENARIO[:4]})

    assert response.status_code == 422
    assert "score" not in response.json()


def test_web_app_is_served_from_the_same_origin() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Соберите план действий" in response.text
