from __future__ import annotations

import json
from io import BytesIO

from backend.app.ai import explain
from backend.app.engine import simulate

REFERENCE_SCENARIO = [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12", "district_id": None},
    {"measure_id": "M5", "district_id": "saryarka"},
]


def test_fallback_explicitly_explains_future_consequences(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = explain(simulate(REFERENCE_SCENARIO))

    assert result["source"] == "rules"
    assert len(result["consequences"]) == 2
    assert "Нура" in result["consequences"][0]
    assert "ни один показатель" in result["consequences"][1]


def test_provider_prose_is_allowed_only_without_numeric_claims(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_provider(request, timeout):
        payload = json.loads(request.data)
        assert payload["model"]
        assert "districts" in payload["messages"][1]["content"]
        assert "measure_effects" in payload["messages"][1]["content"]
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "summary": "Социальная инфраструктура растёт в слабейшем районе.",
                                "strengths": ["Школы становятся доступнее."],
                                "risks": ["Остаётся разрыв между районами."],
                                "consequences": ["Нура улучшит социальные показатели."],
                                "recommendations": ["Сравните городской транспорт и качество воздуха."],
                            }
                        )
                    }
                }
            ]
        }
        return BytesIO(json.dumps(response).encode())

    monkeypatch.setattr("backend.app.ai.urlopen", fake_provider)
    result = explain(simulate(REFERENCE_SCENARIO))

    assert result["source"] == "openai"
    assert result["status"] == "ok"
    assert result["consequences"] == ["Нура улучшит социальные показатели."]


def test_fabricated_ai_score_falls_back_to_engine_values(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fabricated_provider(request, timeout):
        content = json.dumps(
            {
                "summary": "Итоговый Score составил 99.99.",
                "strengths": ["Показатели растут."],
                "risks": ["Есть компромиссы."],
                "consequences": ["Город станет доступнее."],
                "recommendations": ["Сравните сценарии."],
            }
        )
        return BytesIO(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    monkeypatch.setattr("backend.app.ai.urlopen", fabricated_provider)
    report = simulate(REFERENCE_SCENARIO)
    result = explain(report)

    assert result["source"] == "rules"
    assert "99.99" not in result["summary"]
    assert f"{report['score']:.2f}" in result["summary"]
