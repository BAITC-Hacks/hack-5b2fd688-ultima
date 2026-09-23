"""Optional AI selection of verified facts; all displayed prose is server-authored."""

from __future__ import annotations

import json
import os
from http.client import HTTPException as HTTPClientError
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .evidence import SECTIONS, build_fact_catalog, fallback_selection, render_selection

MAX_SECTION_ITEMS = 3


def _facts_for_model(
    report: dict[str, Any], alternatives: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "model_version": report["model_version"],
        "required_summary_fact": "scenario",
        "catalog": build_fact_catalog(report, alternatives),
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("AI response contains a duplicate field")
        result[key] = value
    return result


def _normalise_model_response(content: str, catalog: list[dict[str, Any]]) -> dict[str, list[str]]:
    parsed = json.loads(content, object_pairs_hook=_unique_object)
    if not isinstance(parsed, dict) or set(parsed) != set(SECTIONS):
        raise ValueError("AI response does not match the exact selection schema")
    by_id = {fact["id"]: fact for fact in catalog}
    for section in SECTIONS:
        chosen = parsed[section]
        if not isinstance(chosen, list) or not 1 <= len(chosen) <= MAX_SECTION_ITEMS:
            raise ValueError("AI response must contain one to three IDs per section")
        if any(not isinstance(fact_id, str) or fact_id not in by_id for fact_id in chosen):
            raise ValueError("AI response contains an unknown fact ID or invalid type")
        if len(chosen) != len(set(chosen)):
            raise ValueError("AI response repeats a fact within a section")
        if any(section not in by_id[fact_id]["allowed_sections"] for fact_id in chosen):
            raise ValueError("AI response assigns a fact to an incompatible section")
    if "scenario" not in parsed["summary"]:
        raise ValueError("AI response omits the mandatory scenario summary")
    return parsed


def _selection_schema(catalog: list[dict[str, Any]]) -> dict[str, Any]:
    """Constrain provider decoding to valid IDs and the report's section sizes."""
    return {
        "type": "object",
        "properties": {
            section: {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["scenario"] if section == "summary" else [
                        fact["id"] for fact in catalog if section in fact["allowed_sections"]
                    ],
                },
                "minItems": 1,
                "maxItems": 1 if section == "summary" else MAX_SECTION_ITEMS,
            }
            for section in SECTIONS
        },
        "required": list(SECTIONS),
        "additionalProperties": False,
    }


def explain(
    report: dict[str, Any], alternatives: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Ask a Chat Completions endpoint to prioritize facts, with a grounded fallback."""
    facts = _facts_for_model(report, alternatives)
    catalog = facts["catalog"]
    fallback = render_selection(fallback_selection(catalog, critical_count=report["critical_count"]), catalog)
    fallback_note = "Факты и формулировки проверены локальной расчётной моделью; акценты выбраны автоматически."
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            **fallback,
            "source": "rules",
            "status": "fallback",
            "note": f"AI-ключ не настроен. {fallback_note}",
        }

    system_message = (
        "Ты аналитик симулятора города на синтетических данных. Выбери самые содержательные "
        "и важные факты из серверного каталога для объяснения сценария. Не пиши собственный текст: "
        "сервер покажет только проверенные канонические формулировки выбранных фактов. "
        "Верни только JSON-объект ровно с полями summary, strengths, risks, consequences, "
        "recommendations. Каждое поле — массив из 1–3 различных существующих fact IDs (строк). "
        "Факт разрешён только в разделах из его allowed_sections. "
        "В summary верни только [\"scenario\"] с итоговым Score и бюджетом. "
        "В strengths предпочитай самые большие улучшения, синергии и городские эффекты. "
        "В risks предпочитай критические и самые низкие неизменённые показатели, отрицательные "
        "вклады мер и лаги, а не общий факт бюджета. В consequences покажи распределение эффектов "
        "между районами, смену слабейшего и критический штраф. Не дублируй факты между разделами "
        "без необходимости. В recommendations выбирай лучшие проверенные альтернативы (alternative.1 "
        "предпочтительна) с выгодами и потерями относительно текущего плана, либо alternatives.none, "
        "если она есть в каталоге. Анализируй числовые доказательства details, но не добавляй ни "
        "своих фактов, ни текста, ни полей. Лаг — уже реализованная доля, а не вероятность."
    )
    request_body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "temperature": 0.2,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "verified_city_analysis",
                "strict": True,
                "schema": _selection_schema(catalog),
            },
        },
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
    }
    request = Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=18) as response:
            response_json = json.loads(response.read().decode("utf-8"))
        content = response_json["choices"][0]["message"]["content"]
        selection = _normalise_model_response(content, catalog)
        return {
            **render_selection(selection, catalog),
            "source": "openai",
            "status": "ok",
            "note": "AI выбрал акценты; факты и формулировки проверены локальной расчётной моделью.",
        }
    except (OSError, HTTPClientError, KeyError, IndexError, TypeError, ValueError) as error:
        reason = "не удалось получить корректный выбор фактов"
        if isinstance(error, HTTPError):
            reason = f"провайдер вернул HTTP {error.code}"
        elif isinstance(error, (OSError, HTTPClientError)):
            reason = "AI-сервис временно недоступен"
        return {
            **fallback,
            "source": "rules",
            "status": "fallback",
            "note": f"Встроенное объяснение: {reason}. {fallback_note}",
        }
