from __future__ import annotations

import pytest

from backend.app.engine import baseline_report, simulate, validate_choices


REFERENCE_SCENARIO = [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12", "district_id": None},
    {"measure_id": "M5", "district_id": "saryarka"},
]


def test_baseline_matches_dataset_reference() -> None:
    report = baseline_report()

    assert report["score"] == pytest.approx(52.55768)
    assert report["districts"][0]["score_before"] == pytest.approx(62.99)
    assert report["districts"][-1]["score_after"] == pytest.approx(49.18)
    assert report["critical_count"] == 2


def test_documented_scenario_matches_reference_score_and_budget() -> None:
    report = simulate(REFERENCE_SCENARIO)

    assert report["total_cost"] == 95
    assert report["budget_remaining"] == 5
    assert report["score"] == pytest.approx(56.54307)
    assert report["score_delta"] == pytest.approx(3.98539)
    assert report["critical_count"] == 0
    assert report["applied_synergies"][0]["measures"] == ["M10", "M12"]
    assert report["weakest_district_name"] == "Нура"


def test_synergy_bonus_is_not_scaled_by_measure_lag() -> None:
    report = simulate(REFERENCE_SCENARIO)
    nura_safety = next(
        indicator
        for district in report["districts"]
        if district["id"] == "nura"
        for indicator in district["indicators"]
        if indicator["id"] == "B1"
    )

    # M10 contributes 12 * 7/8; M10+M12 adds its fixed +2 synergy.
    assert nura_safety["after"] - nura_safety["before"] == pytest.approx(12.5)


def test_measure_order_does_not_change_score() -> None:
    forward = simulate(REFERENCE_SCENARIO)
    backward = simulate(list(reversed(REFERENCE_SCENARIO)))

    assert backward["score"] == pytest.approx(forward["score"])
    assert backward["districts"] == forward["districts"]


def test_citywide_measure_applies_to_each_district() -> None:
    report = simulate(REFERENCE_SCENARIO)
    city_platform_changes = [
        change
        for change in report["indicator_changes"]
        if change["id"] == "C2" and change["district_id"] != "saryarka"
    ]

    assert len(city_platform_changes) == 4
    assert all(change["delta"] == pytest.approx(4.375) for change in city_platform_changes)


def test_district_measure_only_changes_selected_district() -> None:
    report = simulate(REFERENCE_SCENARIO)
    school_changes = [change for change in report["indicator_changes"] if change["id"] == "S1"]

    assert len(school_changes) == 1
    assert school_changes[0]["district_id"] == "nura"
    assert school_changes[0]["after"] == pytest.approx(48)


def test_incomplete_selection_can_be_valid_but_is_not_ready() -> None:
    result = validate_choices(REFERENCE_SCENARIO[:3])

    assert result["valid"] is True
    assert result["ready"] is False
    assert result["remaining_selections"] == 2


def test_final_calculation_requires_exactly_five_measures() -> None:
    result = validate_choices(REFERENCE_SCENARIO[:4], require_five=True)

    assert result["valid"] is False
    assert any("ровно 5" in error for error in result["errors"])


def test_duplicate_measure_is_rejected() -> None:
    result = validate_choices(
        [
            {"measure_id": "M12", "district_id": None},
            {"measure_id": "M12", "district_id": None},
        ]
    )

    assert result["valid"] is False
    assert any("повторно" in error for error in result["errors"])


def test_budget_overrun_is_rejected() -> None:
    over_budget = [
        {"measure_id": "M3", "district_id": "esil"},
        {"measure_id": "M5", "district_id": "saryarka"},
        {"measure_id": "M7", "district_id": "nura"},
        {"measure_id": "M8", "district_id": "nura"},
        {"measure_id": "M13", "district_id": "almaty"},
    ]

    result = validate_choices(over_budget, require_five=True)

    assert result["total_cost"] == 127
    assert result["valid"] is False
    assert any("Бюджет превышен" in error for error in result["errors"])


def test_city_measure_rejects_a_district_assignment() -> None:
    result = validate_choices([{"measure_id": "M12", "district_id": "nura"}])

    assert result["valid"] is False
    assert any("район выбирать не нужно" in error for error in result["errors"])


@pytest.mark.parametrize(
    ("first", "second", "first_district", "second_district", "expected_valid"),
    [
        ("M1", "M3", "esil", "nura", False),
        ("M4", "M7", "nura", "nura", False),
        ("M4", "M7", "esil", "nura", True),
        ("M5", "M13", "almaty", "almaty", False),
        ("M5", "M13", "saryarka", "almaty", True),
    ],
)
def test_incompatibility_rules(
    first: str,
    second: str,
    first_district: str,
    second_district: str,
    expected_valid: bool,
) -> None:
    result = validate_choices(
        [
            {"measure_id": first, "district_id": first_district},
            {"measure_id": second, "district_id": second_district},
        ]
    )

    assert result["valid"] is expected_valid


def test_more_than_two_measures_in_one_direction_is_rejected() -> None:
    result = validate_choices(
        [
            {"measure_id": "M1", "district_id": "esil"},
            {"measure_id": "M2", "district_id": None},
            {"measure_id": "M3", "district_id": "nura"},
        ]
    )

    assert result["valid"] is False
    assert any("максимум — 2" in error for error in result["errors"])


def test_partial_selection_rejects_unknown_measure() -> None:
    result = validate_choices([{"measure_id": "M99", "district_id": None}])

    assert result["valid"] is False
    assert any("неизвестное мероприятие" in error for error in result["errors"])
