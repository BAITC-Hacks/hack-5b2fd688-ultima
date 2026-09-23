from backend.app.engine import simulate, validate_choices
from backend.app.recommender import recommend_alternatives


REFERENCE_SCENARIO = [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12", "district_id": None},
    {"measure_id": "M5", "district_id": "saryarka"},
]


def test_recommendations_are_valid_single_change_improvements() -> None:
    current_report = simulate(REFERENCE_SCENARIO)
    result = recommend_alternatives(REFERENCE_SCENARIO, current_report=current_report)

    assert result["alternatives"]
    scores = [alternative["score"] for alternative in result["alternatives"]]
    assert scores == sorted(scores, reverse=True)

    for alternative in result["alternatives"]:
        assert round(alternative["score"], 2) > round(current_report["score"], 2)
        assert alternative["display_score_delta"] == round(
            round(alternative["score"], 2) - round(current_report["score"], 2), 2
        )
        assert alternative["total_cost"] <= 100
        assert validate_choices(alternative["selections"], require_five=True)["valid"] is True
        changed_slots = sum(
            old != new
            for old, new in zip(REFERENCE_SCENARIO, alternative["selections"], strict=True)
        )
        assert changed_slots == 1


def test_recommendations_include_actionable_precalculated_details() -> None:
    result = recommend_alternatives(REFERENCE_SCENARIO)
    best = result["alternatives"][0]

    assert "Заменить" in best["description"] or "Перенести" in best["description"]
    assert best["score_delta"] > 0
    assert len(best["selections"]) == 5
