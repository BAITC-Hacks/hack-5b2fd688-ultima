from __future__ import annotations

import json
from io import BytesIO

import pytest

from backend.app.ai import _facts_for_model, explain
from backend.app.engine import simulate
from backend.app.recommender import recommend_alternatives

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


@pytest.mark.parametrize("empty_field", ["summary", "strengths", "risks", "consequences", "recommendations"])
def test_empty_provider_analysis_uses_factual_fallback(monkeypatch, empty_field: str) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    content = {
        "summary": "Решения улучшают районы.",
        "strengths": ["Расширяется доступность услуг."],
        "risks": ["Сохраняются различия между районами."],
        "consequences": ["Слабейший район остаётся приоритетным."],
        "recommendations": ["Сравните другие планы."],
    }
    content[empty_field] = "   " if empty_field == "summary" else ["   "]

    def empty_provider(request, timeout):
        return BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode())

    monkeypatch.setattr("backend.app.ai.urlopen", empty_provider)
    result = explain(simulate(REFERENCE_SCENARIO))

    assert result["source"] == "rules"
    assert result["status"] == "fallback"
    assert result["summary"].strip()


def test_ai_facts_include_engine_attribution_and_checked_alternative_tradeoffs() -> None:
    report = simulate(REFERENCE_SCENARIO)
    alternatives = recommend_alternatives(REFERENCE_SCENARIO, current_report=report)[
        "alternatives"
    ]
    facts = _facts_for_model(report, alternatives)

    school = next(
        effect
        for effect in facts["measure_effects"]
        if effect["source_id"] == "M7" and effect["indicator_id"] == "S1"
    )
    assert school["full_effect"] == 16
    assert school["realised_effect_before_clipping"] == 10
    assert facts["score_components"]["weakest_district_score"] == pytest.approx(52.9625)
    tradeoffs = facts["precalculated_alternatives"][0][
        "indicator_differences_from_current_plan"
    ]
    assert any(item["district"] == "Нура" and item["difference"] > 0 for item in tradeoffs)
    assert any(item["district"] == "Сарыарка" and item["difference"] < 0 for item in tradeoffs)


def test_fallback_describes_a_verified_loss_in_the_best_replacement(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = simulate(REFERENCE_SCENARIO)
    alternatives = recommend_alternatives(REFERENCE_SCENARIO, current_report=report)[
        "alternatives"
    ]

    explanation = explain(report, alternatives)

    assert explanation["source"] == "rules"
    assert "Качество воздуха" in explanation["recommendations"][0]
    assert "Сарыарка" in explanation["recommendations"][0]
