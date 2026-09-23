from __future__ import annotations

import json
from http.client import IncompleteRead
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from backend.app.ai import _facts_for_model, _normalise_model_response, explain
from backend.app.engine import MEASURES, baseline_report, simulate
from backend.app.evidence import SECTIONS, build_fact_catalog
from backend.app.recommender import recommend_alternatives

REFERENCE_SCENARIO = [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12", "district_id": None},
    {"measure_id": "M5", "district_id": "saryarka"},
]


@pytest.fixture(autouse=True)
def offline_ai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def unexpected_network(*args, **kwargs):
        pytest.fail("Tests must never contact a real AI provider")

    monkeypatch.setattr("backend.app.ai.urlopen", unexpected_network)


@pytest.fixture(scope="module")
def report():
    return simulate(REFERENCE_SCENARIO)


@pytest.fixture(scope="module")
def catalog(report):
    return build_fact_catalog(report)


def model_content() -> dict:
    return {
        "summary": ["scenario"],
        "strengths": ["gain.nura.S1", "synergy.M10.M12"],
        "risks": ["indicators.unchanged", "effects.lag"],
        "consequences": ["district.weakest", "critical", "city.M12"],
        "recommendations": ["alternative.1"],
    }


def provider_body(content) -> bytes:
    return json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()


def mock_model_content(monkeypatch, content) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("backend.app.ai.urlopen", lambda request, timeout: BytesIO(provider_body(content)))


def assert_evidence_contract(result, catalog) -> None:
    by_id = {fact["id"]: fact for fact in catalog}
    assert result["grounding"] == "verified_fact_selection"
    assert set(result["evidence"]) == set(SECTIONS)
    for section in SECTIONS:
        evidence = result["evidence"][section]
        assert 1 <= len(evidence) <= 3
        assert len({fact["id"] for fact in evidence}) == len(evidence)
        for fact in evidence:
            assert set(fact) == {"id", "text", "details"}
            canonical = by_id[fact["id"]]
            assert section in canonical["allowed_sections"]
            assert fact["text"] == canonical["text"]
            assert fact["details"] == canonical["details"]
            assert fact["details"] and all(isinstance(detail, str) and detail for detail in fact["details"])
        text = [fact["text"] for fact in evidence]
        assert result[section] == (" ".join(text) if section == "summary" else text)
    assert "scenario" in {fact["id"] for fact in result["evidence"]["summary"]}


def test_fallback_is_deterministic_grounded_and_substantive(report, catalog) -> None:
    result = explain(report)

    assert result == explain(report)
    assert result["source"] == "rules"
    assert result["status"] == "fallback"
    assert "AI-ключ не настроен" in result["note"]
    assert "акценты выбраны автоматически" in result["note"]
    assert "Нура" in result["consequences"][0]
    assert "остаётся слабейшим" in result["consequences"][0]
    assert "ни один показатель" in result["consequences"][1]
    assert {fact["id"] for fact in result["evidence"]["strengths"]} == {
        "gain.nura.B1", "synergy.M10.M12", "district.most_improved"
    }
    assert "indicators.unchanged" in {fact["id"] for fact in result["evidence"]["risks"]}
    assert "budget" not in {fact["id"] for fact in result["evidence"]["risks"]}
    assert_evidence_contract(result, catalog)


def test_real_transport_path_accepts_only_id_selection_and_renders_server_text(monkeypatch, report, catalog) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    calls = []

    def fake_provider(request, timeout):
        calls.append(request)
        assert request.full_url == "https://api.openai.com/v1/chat/completions"
        assert request.method == "POST"
        assert request.get_header("Authorization") == "Bearer test-key"
        assert timeout == 18
        payload = json.loads(request.data)
        assert payload["model"] == "gpt-4.1-mini"
        assert payload["response_format"]["type"] == "json_schema"
        schema = payload["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["additionalProperties"] is False
        assert schema["schema"]["properties"]["summary"]["items"]["enum"] == ["scenario"]
        for section in SECTIONS[1:]:
            field = schema["schema"]["properties"][section]
            assert (field["minItems"], field["maxItems"]) == (1, 3)
            assert set(field["items"]["enum"]) == {
                fact["id"] for fact in catalog if section in fact["allowed_sections"]
            }
        facts = json.loads(payload["messages"][1]["content"])
        assert facts["catalog"] == catalog
        assert facts["required_summary_fact"] == "scenario"
        return BytesIO(provider_body(model_content()))

    monkeypatch.setattr("backend.app.ai.urlopen", fake_provider)
    result = explain(report)

    assert len(calls) == 1
    assert result["source"] == "openai"
    assert result["status"] == "ok"
    assert "AI выбрал акценты" in result["note"]
    assert "Школы и детсады" in result["strengths"][0]
    assert "38 → 48 (+10 пункта)" in result["strengths"][0]
    assert result["strengths"][0] != model_content()["strengths"][0]
    assert_evidence_contract(result, catalog)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("summary", "scenario"),
        ("summary", []),
        ("summary", ["city.average"]),  # Mandatory total may not be omitted.
        ("summary", ["scenario", "scenario"]),
        ("strengths", ["unknown.fact"]),
        ("strengths", ["gain.nura.S1", "gain.nura.S1"]),
        ("strengths", ["gain.nura.S1", "gain.nura.B1", "synergy.M10.M12", "city.average"]),
        ("strengths", ["indicators.unchanged"]),  # A known ID is not valid in every section.
        ("risks", [True]),
        ("risks", [7]),
        ("risks", [None]),
        ("risks", [["effects.lag"]]),
        ("consequences", None),
        ("recommendations", ["scenario"]),
        ("recommendations", {}),
        ("strengths", [{"id": "gain.nura.S1", "text": "Жители перестанут болеть."}]),
        ("consequences", ["district.weakest", "Район перестанет быть слабейшим."]),
        ("recommendations", ["alternative.1", "Score теперь 99.99"]),
        ("risks", ["effects.lag\u200b"]),
        ("risks", ["effects.lag\x00"]),
    ],
)
def test_invalid_selection_uses_complete_verified_fallback(monkeypatch, report, catalog, field, invalid_value) -> None:
    mock_model_content(monkeypatch, {**model_content(), field: invalid_value})

    result = explain(report)

    assert result["source"] == "rules"
    assert result["status"] == "fallback"
    assert "56.54" in result["summary"]
    assert "корректный выбор фактов" in result["note"]
    assert_evidence_contract(result, catalog)
    assert "Жители перестанут болеть" not in json.dumps(result, ensure_ascii=False)
    assert "99.99" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize("field", SECTIONS)
def test_missing_or_empty_sections_are_rejected(monkeypatch, report, field) -> None:
    for content in ({key: value for key, value in model_content().items() if key != field},
                    {**model_content(), field: []}):
        mock_model_content(monkeypatch, content)
        assert explain(report)["source"] == "rules"


@pytest.mark.parametrize("extra_field", ["text", "evidence", "note", "grounding", "source"])
def test_known_ids_with_extra_prose_or_provider_metadata_are_rejected(monkeypatch, report, extra_field) -> None:
    mock_model_content(monkeypatch, {**model_content(), extra_field: "Нура станет самым богатым районом."})
    result = explain(report)
    assert result["source"] == "rules"
    assert "Нура станет самым богатым" not in json.dumps(result, ensure_ascii=False)


def test_duplicate_json_keys_are_not_silently_overwritten(catalog) -> None:
    content = json.dumps(model_content())
    duplicate = content[:-1] + ', "summary": ["scenario"]}'
    with pytest.raises(ValueError, match="duplicate field"):
        _normalise_model_response(duplicate, catalog)


def test_prose_only_hallucinations_without_digits_are_rejected(monkeypatch, report) -> None:
    mock_model_content(monkeypatch, {
        "summary": "Доверие жителей вырастет.",
        "strengths": ["Школы полностью ликвидируют дефицит мест."],
        "risks": ["Вероятен срыв работ."],
        "consequences": ["Нура станет самым сильным районом."],
        "recommendations": ["Увеличить финансирование."],
    })
    result = explain(report)
    assert result["source"] == "rules"
    assert "срыв работ" not in json.dumps(result, ensure_ascii=False)


def test_three_items_and_multiple_summary_facts_are_valid(monkeypatch, report, catalog) -> None:
    content = model_content()
    content["summary"] = ["scenario", "city.average"]
    content["strengths"] = ["gain.nura.S1", "synergy.M10.M12", "gain.nura.B1"]
    content["recommendations"] = ["alternative.1", "alternative.2", "alternative.3"]
    mock_model_content(monkeypatch, content)

    result = explain(report)

    assert result["source"] == "openai"
    assert len(result["strengths"]) == len(result["recommendations"]) == 3
    assert_evidence_contract(result, catalog)


def test_catalog_has_compact_numerical_evidence_for_lags_synergy_and_city_effects(report) -> None:
    facts = _facts_for_model(report, None)
    by_id = {fact["id"]: fact for fact in facts["catalog"]}
    assert len(by_id) == len(facts["catalog"])
    assert len(by_id) < 25  # Material facts, rather than one generic claim for every indicator.
    for fact in by_id.values():
        assert set(fact) == {"id", "text", "details", "allowed_sections"}
        assert fact["details"]
        assert set(fact["allowed_sections"]).issubset(SECTIONS)
    assert "62.5%" in by_id["effects.lag"]["text"]
    assert "не вероятность и не прогноз" in by_id["effects.lag"]["text"]
    assert any("M7" in detail and "+16 × 0.625 = +10" in detail for detail in by_id["effects.lag"]["details"])
    assert "+2 пункта" in by_id["synergy.M10.M12"]["text"]
    assert "не отдельный аддитивный вклад в Score" in by_id["synergy.M10.M12"]["details"][1]
    assert "во всех районах" in by_id["city.M12"]["text"]
    assert len(by_id["city.M12"]["details"]) == 5
    assert all("+5 × 0.875 = +4.375" in detail for detail in by_id["city.M12"]["details"])
    assert "Общественный транспорт» в районе Нура — 40" in by_id["indicators.unchanged"]["text"]
    assert "штраф за критические показатели равен нулю" in by_id["critical"]["text"]
    assert "Число критических показателей: 2 → 0; изменение штрафного слагаемого Score: +2." in by_id["critical"]["details"]


def test_alternatives_are_recomputed_and_losses_are_relative_to_current_plan(report) -> None:
    alternatives = recommend_alternatives(REFERENCE_SCENARIO, current_report=report)["alternatives"]
    falsified_metadata = [{**alternative, "score": 99.99, "description": "Ложный текст провайдера", "score_delta": 999}
                         for alternative in reversed(alternatives)]
    facts = build_fact_catalog(report, falsified_metadata)
    best = next(fact for fact in facts if fact["id"] == "alternative.1")

    assert "Score 57.21 (+0.67" in best["text"]
    assert "Общественный транспорт» в районе Нура — 40 → 50 (+10)" in best["text"]
    assert "Качество воздуха» в районе Сарыарка — 48.75 → 40 (-8.75)" in best["text"]
    assert "относительно текущего плана" in best["text"]
    assert "Вариант не применён" in best["text"]
    assert "99.99" not in str(best)
    assert "Ложный текст" not in str(best)
    assert any("56.54307 → 57.20556" in detail for detail in best["details"])
    assert any("не с исходным городом" in detail for detail in best["details"])
    assert best["allowed_sections"] == ["recommendations"]


@pytest.mark.parametrize("invalid_plan", [
    REFERENCE_SCENARIO,  # A zero delta is not an improvement.
    REFERENCE_SCENARIO[:4],  # Incomplete plan.
    [{"measure_id": "M7", "district_id": "esil"}, *REFERENCE_SCENARIO[1:]],  # Worse Score.
    [{"measure_id": "M7", "district_id": "esil"},
     {"measure_id": "M8", "district_id": "saryarka"}, *REFERENCE_SCENARIO[2:]],  # Two replacements.
    [{"measure_id": "M99", "district_id": "nura"}, *REFERENCE_SCENARIO[1:]],
])
def test_unverified_alternatives_are_not_advertised(report, invalid_plan) -> None:
    invalid = {"selections": invalid_plan, "score": 99.99, "description": "FAKE_RECOMMENDATION"}
    facts = build_fact_catalog(report, [invalid])
    recommendations = [fact for fact in facts if "recommendations" in fact["allowed_sections"]]
    assert recommendations
    assert all("FAKE_RECOMMENDATION" not in fact["text"] for fact in recommendations)
    assert recommendations[0]["id"] == "alternative.1"
    assert "Score 57.21" in recommendations[0]["text"]


def test_no_alternatives_claim_requires_an_actual_search(report) -> None:
    # Omitting caller suggestions must not be interpreted as proof of optimality.
    assert any(fact["id"] == "alternative.1" for fact in build_fact_catalog(report, []))
    optimum = simulate([*REFERENCE_SCENARIO[:4], {"measure_id": "M3", "district_id": "nura"}])
    result = explain(optimum, [])
    assert [fact["id"] for fact in result["evidence"]["recommendations"]] == ["alternatives.none"]
    assert "при отображении до сотых" in result["recommendations"][0]


def test_fallback_explains_when_an_unchanged_district_becomes_weakest() -> None:
    report = simulate([{"measure_id": measure_id, "district_id": "nura"}
                       for measure_id in ("M3", "M7", "M8", "M10", "M11")])

    assert report["weakest_district_name"] == "Сарыарка"
    consequence = explain(report)["consequences"][0]
    assert "Сарыарка" in consequence
    assert "не меняется (54.65 балла)" in consequence
    assert "становится слабейшим" in consequence
    assert "остаётся слабейшим" not in consequence
    assert "+0.00" not in consequence


def test_equal_maximum_district_improvements_name_all_ties(monkeypatch) -> None:
    # Equal school/clinic effects produce a real engine-level tie, modulo float noise.
    monkeypatch.setitem(MEASURES["M8"]["effects"], "S2", 16)
    report = simulate([
        {"measure_id": "M7", "district_id": "nura"},
        {"measure_id": "M8", "district_id": "saryarka"},
        {"measure_id": "M6", "district_id": None},
        {"measure_id": "M12", "district_id": None},
        {"measure_id": "M11", "district_id": "almaty"},
    ])
    fact = next(fact for fact in build_fact_catalog(report) if fact["id"] == "district.most_improved")
    assert "Сарыарка, Нура" in fact["text"]
    assert "одинаков у нескольких районов" in fact["text"]


def test_no_positive_delta_is_not_described_as_an_improvement() -> None:
    result = explain(baseline_report())
    assert result["strengths"] == ["В этом расчёте нет показателей с положительным изменением."]
    assert "не меняется (49.18 балла)" in result["consequences"][0]
    assert "district.most_improved" not in str(result["evidence"])


def test_negative_m11_effect_and_new_critical_indicator_have_numeric_proof() -> None:
    choices = [*REFERENCE_SCENARIO[:4], {"measure_id": "M11", "district_id": "almaty"}]
    report = simulate(choices)
    facts = {fact["id"]: fact for fact in build_fact_catalog(report)}
    assert "Алматы — 40 → 38.25 (-1.75)" in facts["indicators.decreased"]["text"]
    assert "-1.75 пункта" in facts["effects.negative"]["text"]
    assert "M11: полный эффект -2 × реализованная доля 0.875 = -1.75." in facts["effects.negative"]["details"]
    assert "Разгрузка дорог» — Алматы (38.25)" in facts["critical"]["text"]
    result = explain(report)
    assert result["evidence"]["risks"][0]["id"] == "critical"
    assert "indicators.decreased" in {fact["id"] for fact in result["evidence"]["risks"]}


def test_negative_contribution_is_not_confused_with_net_decline() -> None:
    report = simulate([
        {"measure_id": "M1", "district_id": "nura"},
        {"measure_id": "M2", "district_id": None},
        {"measure_id": "M11", "district_id": "nura"},
        {"measure_id": "M12", "district_id": None},
        {"measure_id": "M9", "district_id": "nura"},
    ])
    facts = {fact["id"]: fact for fact in build_fact_catalog(report)}
    assert "indicators.decreased" not in facts
    assert "effects.negative" in facts
    assert "до ограничения шкалы" in facts["effects.negative"]["text"]
    assert "Итоговое изменение учитывает также остальные меры" in facts["effects.negative"]["text"]


def test_indicator_gain_and_source_contribution_are_distinct_when_clipped(monkeypatch) -> None:
    monkeypatch.setitem(MEASURES["M7"]["effects"], "S1", 160)
    report = simulate(REFERENCE_SCENARIO)
    fact = next(fact for fact in build_fact_catalog(report) if fact["id"] == "gain.nura.S1")
    assert "38 → 100 (+62 пункта)" in fact["text"]
    assert any("вклад +100 пункта до ограничения шкалы" in detail for detail in fact["details"])


@pytest.mark.parametrize("failure", [
    TimeoutError("timeout"), URLError("offline"),
    HTTPError("https://mock", 429, "rate limit", None, None),
    IncompleteRead(b'{"choices":', 100), ConnectionResetError("connection reset while reading"),
])
def test_provider_transport_errors_preserve_fallback(monkeypatch, report, catalog, failure) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def failed_provider(request, timeout):
        raise failure

    monkeypatch.setattr("backend.app.ai.urlopen", failed_provider)
    result = explain(report)
    assert result["source"] == "rules"
    assert result["status"] == "fallback"
    assert "56.54" in result["summary"]
    assert ("HTTP 429" if isinstance(failure, HTTPError) else "временно недоступен") in result["note"]
    assert_evidence_contract(result, catalog)


@pytest.mark.parametrize("body", [
    b"not json", b"{}", b'{"choices":[]}', b'{"choices":[{"message":{"content":null}}]}',
    b'{"choices":[{"message":{"content":[]}}]}', b'{"choices":[{"message":{"content":"[]"}}]}',
    b'{"choices":[{"message":{"content":"not json"}}]}', b'\xff',
])
def test_malformed_provider_response_preserves_fallback(monkeypatch, report, catalog, body) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("backend.app.ai.urlopen", lambda request, timeout: BytesIO(body))
    result = explain(report)
    assert result["source"] == "rules"
    assert result["status"] == "fallback"
    assert_evidence_contract(result, catalog)
