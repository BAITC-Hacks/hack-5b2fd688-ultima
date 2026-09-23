"""Optional AI narrative. All numerical results come from the scoring engine."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .engine import DATA, DISTRICTS, INDICATORS, simulate


def _alternative_indicator_differences(
    report: dict[str, Any], alternative: dict[str, Any]
) -> list[dict[str, Any]]:
    """Compare two engine reports; never ask the language model to calculate tradeoffs."""
    candidate = simulate(alternative["selections"])
    current_values = {
        (district["id"], indicator["id"]): indicator["after"]
        for district in report["districts"]
        for indicator in district["indicators"]
    }
    return [
        {
            "district": district["name"],
            "indicator": indicator["label"],
            "current_after": current_values[(district["id"], indicator["id"])],
            "alternative_after": indicator["after"],
            "difference": indicator["after"] - current_values[(district["id"], indicator["id"])],
        }
        for district in candidate["districts"]
        for indicator in district["indicators"]
        if abs(indicator["after"] - current_values[(district["id"], indicator["id"])]) > 1e-9
    ]


def _fallback_explanation(
    report: dict[str, Any], alternatives: list[dict[str, Any]]
) -> dict[str, Any]:
    strongest = max(report["indicator_changes"], key=lambda item: item["delta"], default=None)
    strengths: list[str] = []
    if strongest:
        strengths.append(
            f"Сильнее всего вырос показатель «{strongest['label']}» в районе "
            f"{strongest['district_name']}: {strongest['before']:.1f} → {strongest['after']:.1f}."
        )
    weakest = next(
        (item for item in report["districts"] if item["id"] == report["weakest_district_id"]),
        None,
    )
    if weakest:
        strengths.append(
            f"Слабейший район после изменений — {weakest['name']} "
            f"({weakest['score_after']:.2f} балла). Это помогает увидеть, где ещё нужен фокус."
        )
    if report["applied_synergies"]:
        names = [" + ".join(item["measures"]) for item in report["applied_synergies"]]
        strengths.append("Сработала синергия мер: " + ", ".join(names) + ".")

    risks = []
    if report["critical_indicators"]:
        examples = report["critical_indicators"][:3]
        risks.append(
            "Ниже порога 40 остались: "
            + ", ".join(
                f"{item['indicator_label']} в районе {item['district_name']} ({item['value']:.1f})"
                for item in examples
            )
            + (" и другие." if len(report["critical_indicators"]) > len(examples) else ".")
        )
    else:
        risks.append("После выбранных мер показателей ниже критического порога 40 не осталось.")

    negative_changes = [item for item in report["indicator_changes"] if item["delta"] < 0]
    if negative_changes:
        item = min(negative_changes, key=lambda change: change["delta"])
        risks.append(
            f"Проверьте компромисс: «{item['label']}» в районе {item['district_name']} "
            f"изменился на {item['delta']:.1f} пункта."
        )
    else:
        risks.append(
            f"Остаток бюджета — {report['budget_remaining']} из {report['budget']} единиц; "
            "он не добавляет баллы к Score."
        )

    if alternatives:
        compared_indicators = _alternative_indicator_differences(report, alternatives[0])
        lost_gain = min(
            (item for item in compared_indicators if item["difference"] < 0),
            key=lambda item: item["difference"],
            default=None,
        )
        recommendations = [
            (
                f"Проверьте вариант «{alternatives[0]['description']}»: модель даёт "
                f"Score {alternatives[0]['score']:.2f} ({alternatives[0]['display_score_delta']:+.2f} "
                "к текущему сценарию). Это альтернативный расчёт, а не применённое решение."
                + (
                    f" Компромисс: «{lost_gain['indicator']}» в районе {lost_gain['district']} "
                    "будет ниже, чем в текущем плане."
                    if lost_gain
                    else ""
                )
            )
        ]
    else:
        recommendations = [
            "Среди допустимых одиночных замен улучшения нет. Попробуйте изменить несколько мер и сравнить результаты."
        ]

    weakest_delta = weakest["score_delta"] if weakest else 0
    consequences = [
        (
            f"К концу модельного горизонта район {weakest['name']} меняется с "
            f"{weakest['score_before']:.2f} до {weakest['score_after']:.2f} балла "
            f"({weakest_delta:+.2f}), но остаётся слабейшим по качеству жизни."
        )
        if weakest
        else "Оценка самых слабых районов остаётся важной при выборе следующих мер.",
        (
            "После мероприятий ни один показатель не остаётся ниже порога 40."
            if report["critical_count"] == 0
            else f"После мероприятий остаётся {report['critical_count']} "
            "показателей ниже порога 40; они сохранят штраф в итоговой оценке."
        ),
    ]

    return {
        "summary": (
            f"Сценарий набрал {report['score']:.2f} из 100 — "
            f"{report['display_score_delta']:+.2f} к базовым {report['baseline_score']:.2f}. "
            f"Потрачено {report['total_cost']} из {report['budget']} условных единиц."
        ),
        "strengths": strengths[:3],
        "risks": risks[:3],
        "consequences": consequences,
        "recommendations": recommendations,
    }


def _facts_for_model(
    report: dict[str, Any], alternatives: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "model_version": report["model_version"],
        "budget": report["budget"],
        "spent": report["total_cost"],
        "remaining": report["budget_remaining"],
        "score": report["score"],
        "score_display": round(report["score"], 2),
        "baseline_score": report["baseline_score"],
        "baseline_score_display": round(report["baseline_score"], 2),
        "score_delta_exact": report["score_delta"],
        "score_delta_display": report["display_score_delta"],
        "city_average": report["city_average"],
        "baseline_city_average": report["baseline_city_average"],
        "weakest_district": report["weakest_district_name"],
        "weakest_district_score": report["weakest_district_score"],
        "score_components": {
            "population_weighted_average": report["city_average"],
            "average_coefficient": 0.7,
            "weakest_district_score": report["weakest_district_score"],
            "weakest_coefficient": 0.3,
            "critical_penalty_per_indicator": 1,
        },
        "critical_count": report["critical_count"],
        "critical_indicators": report["critical_indicators"],
        "selected_measures": report["selected_measures"],
        "districts": [
            {
                "name": district["name"],
                "score_before": district["score_before"],
                "score_after": district["score_after"],
                "indicators": [
                    {
                        "id": indicator["id"],
                        "name": indicator["label"],
                        "before": indicator["before"],
                        "after": indicator["after"],
                        "delta": indicator["delta"],
                    }
                    for indicator in district["indicators"]
                    if indicator["delta"] != 0
                ],
            }
            for district in report["districts"]
        ],
        "synergies": report["applied_synergies"],
        "measure_effects": [
            {
                "source_id": effect["source_id"],
                "source": effect["source_name"],
                "district_id": effect["district_id"],
                "district": DISTRICTS[effect["district_id"]]["name"],
                "indicator_id": effect["indicator_id"],
                "indicator": INDICATORS[effect["indicator_id"]]["label"],
                "full_effect": effect["full_effect"],
                "lag_share": effect["lag_share"],
                "realised_effect_before_clipping": effect["realised_effect"],
                "is_synergy": effect.get("is_synergy", False),
            }
            for effect in report["applied_effects"]
        ],
        "attribution_note": (
            "Measure-level effects are on indicators before clipping. They cannot be added up "
            "as separate Score contributions because the Score has a minimum-district term, "
            "a critical threshold and synergies."
        ),
        "precalculated_alternatives": [
            {
                "description": item["description"],
                "score": item["score"],
                "score_display": round(item["score"], 2),
                "score_delta_exact": item["score_delta"],
                "score_delta_display": item["display_score_delta"],
                "total_cost": item["total_cost"],
                "critical_count": item["critical_count"],
                "weakest_district": item["weakest_district_name"],
                "indicator_differences_from_current_plan": _alternative_indicator_differences(
                    report, item
                ),
            }
            for item in alternatives
        ],
        "indicator_scale": "0–100, higher is better; all values are synthetic.",
        "horizon_quarters": DATA["horizon_quarters"],
    }


def _normalise_model_response(content: str) -> dict[str, Any]:
    parsed = json.loads(content)
    fields = ("summary", "strengths", "risks", "consequences", "recommendations")
    if not isinstance(parsed, dict) or any(field not in parsed for field in fields):
        raise ValueError("AI response does not match the expected schema")
    if not isinstance(parsed["summary"], str) or any(
        not isinstance(parsed[field], list)
        or any(not isinstance(item, str) for item in parsed[field])
        for field in fields[1:]
    ):
        raise ValueError("AI response contains fields with an invalid type")
    if not parsed["summary"].strip() or any(
        not parsed[field] or any(not item.strip() for item in parsed[field])
        for field in fields[1:]
    ):
        raise ValueError("AI response contains an empty analysis")
    # All displayed numbers come from the deterministic report, never from free-form AI prose.
    prose = [parsed["summary"], *(text for field in fields[1:] for text in parsed[field])]
    if any(re.search(r"\d", text) for text in prose):
        raise ValueError("AI response contains numeric claims outside the validated report")
    return {
        "summary": parsed["summary"],
        "strengths": parsed["strengths"][:3],
        "risks": parsed["risks"][:3],
        "consequences": parsed["consequences"][:3],
        "recommendations": parsed["recommendations"][:3],
    }


def explain(
    report: dict[str, Any], alternatives: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Ask an OpenAI-compatible Chat Completions endpoint, with a local fallback."""
    alternatives = alternatives or []
    fallback = _fallback_explanation(report, alternatives)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            **fallback,
            "source": "rules",
            "status": "fallback",
            "note": "AI-ключ не настроен. Показано автоматическое объяснение по рассчитанным данным.",
        }

    facts = _facts_for_model(report, alternatives)
    system_message = (
        "Ты аналитик симулятора развития города. Все данные синтетические. "
        "Объясняй выборы понятным русским языком и придерживайся переданных фактов. "
        "Не пересчитывай Score, не выводи новые числовые оценки и не делай фактических "
        "утверждений о реальной Астане. Если факта нет во входных данных, не выдумывай его. "
        "Ответ нужен только качественный: не используй ни одной цифры ни в одном поле. "
        "Вклад отдельной меры в показатель указан до ограничения шкалы, а вклад в Score "
        "не является аддитивным из-за слабейшего района, порога критичности и синергий. "
        "Все подтверждённые числа интерфейс показывает отдельно из расчётного ядра. "
        "Не предлагай конкретные замены от себя. Если используешь precalculated_alternatives, "
        "объясни словами подтверждённые indicator_differences_from_current_plan: "
        "что улучшилось и от чего пришлось отказаться, не называя цифры, коды и новые Score. "
        "Это альтернативы, которые ещё не применены. "
        "Верни только JSON с полями summary (строка), strengths (массив строк), risks "
        "(массив строк), consequences (массив строк), recommendations (массив строк). "
        "Все текстовые поля и массивы должны содержать непустые содержательные ответы. "
        "В consequences опиши возможные последствия на модельном горизонте. Если готовых альтернатив нет, "
        "сообщи об этом без выдуманных вариантов."
    )
    request_body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_message},
            {
                "role": "user",
                "content": "Объясни результат, опираясь только на этот расчёт:\n"
                + json.dumps(facts, ensure_ascii=False),
            },
        ],
    }
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=18) as response:
            response_json = json.loads(response.read().decode("utf-8"))
        content = response_json["choices"][0]["message"]["content"]
        explanation = _normalise_model_response(content)
        return {**explanation, "source": "openai", "status": "ok", "note": None}
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as error:
        # Keep the score and core flow available if the provider or network is unavailable.
        reason = "не удалось получить корректный ответ"
        if isinstance(error, HTTPError):
            reason = f"провайдер вернул HTTP {error.code}"
        elif isinstance(error, (URLError, TimeoutError)):
            reason = "AI-сервис временно недоступен"
        return {
            **fallback,
            "source": "rules",
            "status": "fallback",
            "note": f"Встроенное объяснение: {reason}; числовой расчёт выполнен локально.",
        }
