"""Optional AI narrative. All numerical results come from the scoring engine."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .engine import DATA


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
        recommendations = [
            (
                f"Проверьте вариант «{alternatives[0]['description']}»: модель даёт "
                f"Score {alternatives[0]['score']:.2f} ({alternatives[0]['display_score_delta']:+.2f} "
                "к текущему сценарию). Это альтернативный расчёт, а не применённое решение."
            )
        ]
    else:
        recommendations = [
            "Среди допустимых одиночных замен улучшения нет. Попробуйте изменить несколько мер и сравнить результаты."
        ]

    return {
        "summary": (
            f"Сценарий набрал {report['score']:.2f} из 100 — "
            f"{report['display_score_delta']:+.2f} к базовым {report['baseline_score']:.2f}. "
            f"Потрачено {report['total_cost']} из {report['budget']} условных единиц."
        ),
        "strengths": strengths[:3],
        "risks": risks[:3],
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
        "weakest_district": report["weakest_district_name"],
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
            }
            for item in alternatives
        ],
        "indicator_scale": "0–100, higher is better; all values are synthetic.",
        "horizon_quarters": DATA["horizon_quarters"],
    }


def _normalise_model_response(content: str) -> dict[str, Any]:
    parsed = json.loads(content)
    fields = ("summary", "strengths", "risks", "recommendations")
    if not isinstance(parsed, dict) or any(field not in parsed for field in fields):
        raise ValueError("AI response does not match the expected schema")
    if not isinstance(parsed["summary"], str) or any(
        not isinstance(parsed[field], list)
        or any(not isinstance(item, str) for item in parsed[field])
        for field in fields[1:]
    ):
        raise ValueError("AI response contains fields with an invalid type")
    return {
        "summary": parsed["summary"],
        "strengths": parsed["strengths"][:3],
        "risks": parsed["risks"][:3],
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
        "Не предлагай конкретные замены от себя. Если используешь precalculated_alternatives, "
        "цитируй только переданные Score и дельты и ясно говори, что это прогнозируемые "
        "альтернативы, которые ещё не применены. Не придумывай новые Score. "
        "Верни только JSON с полями summary (строка), strengths (массив строк), risks "
        "(массив строк), recommendations (массив строк). Если готовых альтернатив нет, "
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
