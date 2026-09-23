"""Find valid, deterministic one-decision improvements for a scenario."""

from __future__ import annotations

from typing import Any

from .engine import DATA, DISTRICTS, MEASURES, simulate, validate_choices


def _as_dict(choice: Any) -> dict[str, Any]:
    if hasattr(choice, "model_dump"):
        return choice.model_dump()
    return {"measure_id": choice["measure_id"], "district_id": choice.get("district_id")}


def _place_name(choice: dict[str, Any]) -> str:
    district_id = choice.get("district_id")
    return DISTRICTS[district_id]["name"] if district_id in DISTRICTS else "весь город"


def recommend_alternatives(
    selections: list[Any],
    *,
    current_report: dict[str, Any] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Return the highest scoring valid plans reachable with one replacement.

    A replacement may change the initiative or move an existing district initiative
    to a different district. Every candidate is validated and scored by the same
    deterministic engine as the user's original scenario.
    """
    current = [_as_dict(choice) for choice in selections]
    if current_report is None:
        current_report = simulate(current)

    selected_ids = {choice["measure_id"] for choice in current}
    seen: set[tuple[tuple[str, str], ...]] = set()
    candidates: list[dict[str, Any]] = []

    for slot, old_choice in enumerate(current):
        old_measure = MEASURES[old_choice["measure_id"]]
        for new_measure in DATA["measures"]:
            if new_measure["id"] in selected_ids and new_measure["id"] != old_measure["id"]:
                continue

            if new_measure["id"] == old_measure["id"]:
                if new_measure["type"] != "district":
                    continue
                places: list[str | None] = [
                    district_id
                    for district_id in DISTRICTS
                    if district_id != old_choice.get("district_id")
                ]
            elif new_measure["type"] == "district":
                places = list(DISTRICTS)
            else:
                places = [None]

            for district_id in places:
                replacement = {"measure_id": new_measure["id"], "district_id": district_id}
                scenario = [dict(choice) for choice in current]
                scenario[slot] = replacement
                validation = validate_choices(scenario, require_five=True)
                if not validation["valid"]:
                    continue

                signature = tuple(
                    sorted(
                        (choice["measure_id"], choice.get("district_id") or "")
                        for choice in scenario
                    )
                )
                if signature in seen:
                    continue
                seen.add(signature)

                candidate_report = simulate(scenario)
                score_gain = candidate_report["score"] - current_report["score"]
                # Only advertise improvements that survive two-decimal display rounding.
                if round(candidate_report["score"], 2) <= round(current_report["score"], 2):
                    continue

                if new_measure["id"] == old_measure["id"]:
                    description = (
                        f"Перенести «{old_measure['name']}»: район "
                        f"{_place_name(old_choice)} → {_place_name(replacement)}"
                    )
                    change_type = "district"
                else:
                    description = (
                        f"Заменить «{old_measure['name']}» ({_place_name(old_choice)}) "
                        f"на «{new_measure['name']}» ({_place_name(replacement)})"
                    )
                    change_type = "measure"

                candidates.append(
                    {
                        "description": description,
                        "change_type": change_type,
                        "score": candidate_report["score"],
                        "score_delta": score_gain,
                        "display_score_delta": round(
                            round(candidate_report["score"], 2)
                            - round(current_report["score"], 2),
                            2,
                        ),
                        "total_cost": candidate_report["total_cost"],
                        "cost_delta": candidate_report["total_cost"] - current_report["total_cost"],
                        "budget_remaining": candidate_report["budget_remaining"],
                        "critical_count": candidate_report["critical_count"],
                        "weakest_district_name": candidate_report["weakest_district_name"],
                        "selections": scenario,
                    }
                )

    candidates.sort(
        key=lambda candidate: (
            -candidate["score"],
            candidate["total_cost"],
            candidate["description"],
        )
    )
    alternatives = candidates[: max(0, limit)]
    return {
        "alternatives": alternatives,
        "searched_candidates": len(seen),
        "message": (
            "Найдены допустимые замены с более высоким Score."
            if alternatives
            else "Среди допустимых одиночных замен варианта с более высоким Score не найдено."
        ),
    }
