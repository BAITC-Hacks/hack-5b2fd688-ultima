"""Deterministic rules, validation, and scoring for the city simulator."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "simulation.json"


def _load_dataset() -> dict[str, Any]:
    with DATA_FILE.open(encoding="utf-8") as file:
        data = json.load(file)

    indicator_ids = {item["id"] for item in data["indicators"]}
    district_ids = {item["id"] for item in data["districts"]}
    measure_ids = {item["id"] for item in data["measures"]}
    if abs(sum(item["weight"] for item in data["indicators"]) - 1) > 1e-9:
        raise ValueError("Indicator weights must add up to 1")
    if abs(sum(item["population_share"] for item in data["districts"]) - 1) > 1e-9:
        raise ValueError("District population shares must add up to 1")
    if any(set(item["indicators"]) != indicator_ids for item in data["districts"]):
        raise ValueError("Every district must define all indicators")
    if any(not set(measure["effects"]).issubset(indicator_ids) for measure in data["measures"]):
        raise ValueError("A measure references an unknown indicator")
    if any(not set(rule["measures"]).issubset(measure_ids) for rule in data["synergies"] + data["incompatibilities"]):
        raise ValueError("A rule references an unknown measure")
    if any(
        not 0 <= value <= 100
        for district in data["districts"]
        for value in district["indicators"].values()
    ):
        raise ValueError("Initial indicators must be in the 0–100 range")
    return data


DATA = _load_dataset()
INDICATORS = {item["id"]: item for item in DATA["indicators"]}
DISTRICTS = {item["id"]: item for item in DATA["districts"]}
MEASURES = {item["id"]: item for item in DATA["measures"]}


def _normalise_choices(choices: list[Any]) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for choice in choices:
        if hasattr(choice, "model_dump"):
            normalised.append(choice.model_dump())
        elif isinstance(choice, dict):
            normalised.append(choice)
        else:
            normalised.append(
                {
                    "measure_id": getattr(choice, "measure_id", None),
                    "district_id": getattr(choice, "district_id", None),
                }
            )
    return normalised


def validate_choices(choices: list[Any], *, require_five: bool = False) -> dict[str, Any]:
    """Validate a partial selection or a complete five-measure scenario."""
    choices = _normalise_choices(choices)
    errors: list[str] = []
    required = DATA["required_selections"]
    known_choices: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    total_cost = 0

    if len(choices) > required:
        errors.append(f"Можно выбрать не больше {required} мероприятий.")
    if require_five and len(choices) != required:
        errors.append(f"Для расчёта нужно выбрать ровно {required} мероприятий; сейчас выбрано {len(choices)}.")

    for index, choice in enumerate(choices, start=1):
        measure_id = choice.get("measure_id")
        district_id = choice.get("district_id")
        if not isinstance(measure_id, str) or measure_id not in MEASURES:
            errors.append(f"Решение {index}: неизвестное мероприятие.")
            continue

        measure = MEASURES[measure_id]
        total_cost += measure["cost"]
        if measure_id in seen:
            errors.append(f"Мероприятие {measure_id} нельзя выбрать повторно.")
        seen.add(measure_id)

        if measure["type"] == "district":
            if not district_id:
                errors.append(f"Для мероприятия {measure_id} «{measure['name']}» выберите район.")
            elif district_id not in DISTRICTS:
                errors.append(f"Для мероприятия {measure_id} указан неизвестный район.")
        elif district_id is not None:
            errors.append(f"Для городского мероприятия {measure_id} район выбирать не нужно.")

        known_choices.append((measure, choice))

    direction_counts = Counter(measure["direction"] for measure, _ in known_choices)
    direction_labels = {measure["direction"]: measure["direction_label"] for measure, _ in known_choices}
    for direction, count in direction_counts.items():
        if count > DATA["max_per_direction"]:
            errors.append(
                f"В направлении «{direction_labels[direction]}» выбрано {count} мероприятия; "
                f"максимум — {DATA['max_per_direction']}."
            )

    if total_cost > DATA["budget"]:
        errors.append(f"Бюджет превышен на {total_cost - DATA['budget']} условных единиц.")

    for rule in DATA["incompatibilities"]:
        first_id, second_id = rule["measures"]
        first_choices = [choice for measure, choice in known_choices if measure["id"] == first_id]
        second_choices = [choice for measure, choice in known_choices if measure["id"] == second_id]
        if not first_choices or not second_choices:
            continue
        conflicts = rule["scope"] == "anywhere" or any(
            first.get("district_id")
            and first.get("district_id") == second.get("district_id")
            for first in first_choices
            for second in second_choices
        )
        if conflicts:
            errors.append(f"{first_id} и {second_id} несовместимы: {rule['description']}")

    # Keep the first occurrence of each message if several conflicting pairs match.
    errors = list(dict.fromkeys(errors))
    return {
        "valid": not errors,
        "ready": not errors and len(choices) == required,
        "errors": errors,
        "selection_count": len(choices),
        "required_selections": required,
        "remaining_selections": max(0, required - len(choices)),
        "total_cost": total_cost,
        "budget": DATA["budget"],
        "budget_remaining": DATA["budget"] - total_cost,
        "direction_counts": dict(direction_counts),
    }


def _score_values(values: dict[str, dict[str, float]]) -> dict[str, Any]:
    district_scores: dict[str, float] = {}
    for district_id, indicators in values.items():
        district_scores[district_id] = sum(
            indicators[indicator_id] * indicator["weight"]
            for indicator_id, indicator in INDICATORS.items()
        )

    city_average = sum(
        DISTRICTS[district_id]["population_share"] * score
        for district_id, score in district_scores.items()
    )
    weakest_id = min(district_scores, key=district_scores.get)
    critical = [
        {"district_id": district_id, "indicator_id": indicator_id, "value": value}
        for district_id, indicators in values.items()
        for indicator_id, value in indicators.items()
        if value < 40
    ]
    score = 0.7 * city_average + 0.3 * district_scores[weakest_id] - len(critical)
    return {
        "score": score,
        "city_average": city_average,
        "weakest_district_id": weakest_id,
        "weakest_district_score": district_scores[weakest_id],
        "district_scores": district_scores,
        "critical_count": len(critical),
        "critical_indicators": critical,
    }


def _build_report(choices: list[dict[str, Any]]) -> dict[str, Any]:
    values = {
        district_id: {indicator_id: float(value) for indicator_id, value in district["indicators"].items()}
        for district_id, district in DISTRICTS.items()
    }
    contributions: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    applied_effects: list[dict[str, Any]] = []
    total_cost = 0

    for choice in choices:
        measure = MEASURES[choice["measure_id"]]
        total_cost += measure["cost"]
        district_ids = list(DISTRICTS) if measure["type"] == "city" else [choice["district_id"]]
        realised_share = (DATA["horizon_quarters"] - measure["lag"]) / DATA["horizon_quarters"]
        for district_id in district_ids:
            for indicator_id, full_effect in measure["effects"].items():
                realised_effect = full_effect * realised_share
                values[district_id][indicator_id] += realised_effect
                contribution = {
                    "source_id": measure["id"],
                    "source_name": measure["name"],
                    "amount": realised_effect,
                }
                contributions[(district_id, indicator_id)].append(contribution)
                applied_effects.append(
                    {
                        "source_id": measure["id"],
                        "source_name": measure["name"],
                        "district_id": district_id,
                        "indicator_id": indicator_id,
                        "full_effect": full_effect,
                        "lag_share": realised_share,
                        "realised_effect": realised_effect,
                    }
                )

    selected_ids = {choice["measure_id"] for choice in choices}
    applied_synergies: list[dict[str, Any]] = []
    for synergy in DATA["synergies"]:
        if not set(synergy["measures"]).issubset(selected_ids):
            continue
        applied_measure = MEASURES[synergy["applied_at"]]
        applied_choice = next(choice for choice in choices if choice["measure_id"] == synergy["applied_at"])
        district_id = (
            applied_choice["district_id"] if applied_measure["type"] == "district" else None
        )
        target_districts = [district_id] if district_id else list(DISTRICTS)
        for target_id in target_districts:
            values[target_id][synergy["indicator"]] += synergy["amount"]
            contributions[(target_id, synergy["indicator"])].append(
                {
                    "source_id": "+".join(synergy["measures"]),
                    "source_name": "Синергия " + " + ".join(synergy["measures"]),
                    "amount": synergy["amount"],
                }
            )
            applied_effects.append(
                {
                    "source_id": "+".join(synergy["measures"]),
                    "source_name": "Синергия " + " + ".join(synergy["measures"]),
                    "district_id": target_id,
                    "indicator_id": synergy["indicator"],
                    "full_effect": synergy["amount"],
                    "lag_share": 1,
                    "realised_effect": synergy["amount"],
                    "is_synergy": True,
                }
            )
        applied_synergies.append(
            {
                "measures": synergy["measures"],
                "indicator_id": synergy["indicator"],
                "amount": synergy["amount"],
                "district_id": district_id,
                "description": synergy["description"],
            }
        )

    district_reports: list[dict[str, Any]] = []
    final_values: dict[str, dict[str, float]] = {}
    all_indicator_changes: list[dict[str, Any]] = []
    for district_id, district in DISTRICTS.items():
        final_values[district_id] = {
            indicator_id: min(100.0, max(0.0, value))
            for indicator_id, value in values[district_id].items()
        }
        indicator_reports: list[dict[str, Any]] = []
        for indicator_id, indicator in INDICATORS.items():
            before = float(district["indicators"][indicator_id])
            after = final_values[district_id][indicator_id]
            delta = after - before
            detail = {
                "id": indicator_id,
                "label": indicator["label"],
                "direction": indicator["direction"],
                "direction_label": indicator["direction_label"],
                "weight": indicator["weight"],
                "before": before,
                "after": after,
                "delta": delta,
                "contributions": contributions[(district_id, indicator_id)],
            }
            indicator_reports.append(detail)
            if delta != 0:
                all_indicator_changes.append(
                    {"district_id": district_id, "district_name": district["name"], **detail}
                )
        district_reports.append(
            {
                "id": district_id,
                "name": district["name"],
                "population_share": district["population_share"],
                "profile": district["profile"],
                "score_before": _score_values(
                    {district_id: district["indicators"]}
                )["district_scores"][district_id],
                "score_after": 0.0,  # Filled after the complete score calculation below.
                "indicators": indicator_reports,
            }
        )

    result = _score_values(final_values)
    baseline_values = {
        district_id: district["indicators"] for district_id, district in DISTRICTS.items()
    }
    baseline = _score_values(baseline_values)
    for district_report in district_reports:
        district_report["score_after"] = result["district_scores"][district_report["id"]]
        district_report["score_delta"] = (
            district_report["score_after"] - district_report["score_before"]
        )

    selected_measures = []
    for choice in choices:
        measure = MEASURES[choice["measure_id"]]
        selected_measures.append(
            {
                "id": measure["id"],
                "name": measure["name"],
                "direction": measure["direction"],
                "direction_label": measure["direction_label"],
                "type": measure["type"],
                "cost": measure["cost"],
                "lag": measure["lag"],
                "district_id": choice["district_id"],
                "district_name": DISTRICTS[choice["district_id"]]["name"]
                if choice["district_id"] in DISTRICTS
                else None,
            }
        )

    return {
        "model_version": DATA["model_version"],
        "budget": DATA["budget"],
        "horizon_quarters": DATA["horizon_quarters"],
        "total_cost": total_cost,
        "budget_remaining": DATA["budget"] - total_cost,
        "score": result["score"],
        "baseline_score": baseline["score"],
        "score_delta": result["score"] - baseline["score"],
        "city_average": result["city_average"],
        "baseline_city_average": baseline["city_average"],
        "weakest_district_id": result["weakest_district_id"],
        "weakest_district_name": DISTRICTS[result["weakest_district_id"]]["name"],
        "weakest_district_score": result["weakest_district_score"],
        "critical_count": result["critical_count"],
        "critical_indicators": [
            {
                **item,
                "district_name": DISTRICTS[item["district_id"]]["name"],
                "indicator_label": INDICATORS[item["indicator_id"]]["label"],
            }
            for item in result["critical_indicators"]
        ],
        "districts": district_reports,
        "selected_measures": selected_measures,
        "applied_synergies": applied_synergies,
        "applied_effects": applied_effects,
        "indicator_changes": all_indicator_changes,
    }


def simulate(choices: list[Any]) -> dict[str, Any]:
    """Return a full report or raise ValueError with user-facing validation errors."""
    validation = validate_choices(choices, require_five=True)
    if not validation["valid"]:
        raise ValueError(" ".join(validation["errors"]))
    return _build_report(_normalise_choices(choices))


def baseline_report() -> dict[str, Any]:
    """Return the fixed initial city score without requiring selected measures."""
    return _build_report([])


def public_config() -> dict[str, Any]:
    """Return the shared, synthetic rules and data used by every simulation."""
    return {
        "model_version": DATA["model_version"],
        "budget": DATA["budget"],
        "horizon_quarters": DATA["horizon_quarters"],
        "required_selections": DATA["required_selections"],
        "max_per_direction": DATA["max_per_direction"],
        "indicators": DATA["indicators"],
        "districts": DATA["districts"],
        "measures": DATA["measures"],
        "synergies": DATA["synergies"],
        "incompatibilities": DATA["incompatibilities"],
        "baseline": baseline_report(),
    }
