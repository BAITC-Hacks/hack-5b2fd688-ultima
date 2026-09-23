from __future__ import annotations

from copy import deepcopy

import pytest

from backend.app.engine import (
    DISTRICTS,
    _score_values,
    baseline_report,
    simulate,
    validate_choices,
)

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


def test_critical_threshold_is_strictly_below_40() -> None:
    values = {
        district_id: dict(district["indicators"])
        for district_id, district in DISTRICTS.items()
    }
    values["nura"]["S1"] = 40
    values["nura"]["S2"] = 39.999

    scored = _score_values(values)

    assert scored["critical_count"] == 1
    assert scored["critical_indicators"][0]["indicator_id"] == "S2"


def test_documented_scenario_matches_reference_score_and_budget() -> None:
    report = simulate(REFERENCE_SCENARIO)

    assert report["total_cost"] == 95
    assert report["budget_remaining"] == 5
    assert report["score"] == pytest.approx(56.54307)
    assert report["score_delta"] == pytest.approx(3.98539)
    assert report["display_score_delta"] == pytest.approx(3.98)
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


@pytest.mark.parametrize(
    ("selections", "synergy_measures", "district_id", "indicator_id"),
    [
        (
            [
                {"measure_id": "M1", "district_id": "esil"},
                {"measure_id": "M2"},
                {"measure_id": "M4", "district_id": "saryarka"},
                {"measure_id": "M10", "district_id": "nura"},
                {"measure_id": "M12"},
            ],
            ["M1", "M2"], "esil", "T1",
        ),
        (
            [
                {"measure_id": "M5", "district_id": "saryarka"},
                {"measure_id": "M6"},
                {"measure_id": "M8", "district_id": "nura"},
                {"measure_id": "M10", "district_id": "nura"},
                {"measure_id": "M12"},
            ],
            ["M5", "M6"], "saryarka", "E2",
        ),
    ],
)
def test_other_synergy_pairs_add_unscaled_bonus_in_the_right_district(
    selections, synergy_measures, district_id, indicator_id
) -> None:
    report = simulate(selections)
    synergy = next(
        item for item in report["applied_synergies"] if item["measures"] == synergy_measures
    )
    indicator = next(
        item
        for district in report["districts"] if district["id"] == district_id
        for item in district["indicators"] if item["id"] == indicator_id
    )

    assert synergy["district_id"] == district_id
    assert synergy["amount"] == 2
    assert any(
        item["source_id"] == "+".join(synergy_measures) and item["amount"] == 2
        for item in indicator["contributions"]
    )


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


def test_citywide_measure_can_omit_district_id_in_direct_engine_calls() -> None:
    without_optional_key = [
        {"measure_id": choice["measure_id"]}
        if choice["measure_id"] == "M12"
        else choice.copy()
        for choice in REFERENCE_SCENARIO
    ]
    report = simulate(without_optional_key)

    assert report["score"] == pytest.approx(56.54307)
    assert report["selected_measures"][3]["district_id"] is None
    assert "district_id" not in without_optional_key[3]


def test_district_measure_only_changes_selected_district() -> None:
    report = simulate(REFERENCE_SCENARIO)
    school_changes = [change for change in report["indicator_changes"] if change["id"] == "S1"]

    assert len(school_changes) == 1
    assert school_changes[0]["district_id"] == "nura"
    assert school_changes[0]["after"] == pytest.approx(48)


def test_negative_crossing_effect_creates_a_new_critical_indicator() -> None:
    report = simulate(
        [
            {"measure_id": "M11", "district_id": "almaty"},
            {"measure_id": "M7", "district_id": "nura"},
            {"measure_id": "M8", "district_id": "nura"},
            {"measure_id": "M5", "district_id": "saryarka"},
            {"measure_id": "M12"},
        ]
    )

    assert report["critical_count"] == 1
    assert report["critical_indicators"][0]["district_id"] == "almaty"
    assert report["critical_indicators"][0]["indicator_id"] == "T1"
    assert report["critical_indicators"][0]["value"] == pytest.approx(38.25)


def test_exactly_100_budget_is_allowed_for_verified_replacement() -> None:
    replacements = [
        {**choice} if choice["measure_id"] != "M5" else {"measure_id": "M3", "district_id": "nura"}
        for choice in REFERENCE_SCENARIO
    ]

    report = simulate(replacements)

    assert report["total_cost"] == 100
    assert report["budget_remaining"] == 0
    assert report["score"] == pytest.approx(57.20556)


def test_incomplete_selection_can_be_valid_but_is_not_ready() -> None:
    result = validate_choices(REFERENCE_SCENARIO[:3])

    assert result["valid"] is True
    assert result["ready"] is False
    assert result["remaining_selections"] == 2


def test_final_calculation_requires_exactly_five_measures() -> None:
    result = validate_choices(REFERENCE_SCENARIO[:4], require_five=True)

    assert result["valid"] is False
    assert any("ровно 5" in error for error in result["errors"])


def test_six_measures_and_unknown_or_missing_districts_are_rejected() -> None:
    too_many = validate_choices(
        [*REFERENCE_SCENARIO, {"measure_id": "M14"}], require_five=True
    )
    missing = validate_choices([{"measure_id": "M7"}])
    unknown = validate_choices([{"measure_id": "M7", "district_id": "other"}])

    assert not too_many["valid"] and any("больше 5" in error for error in too_many["errors"])
    assert any("выберите район" in error for error in missing["errors"])
    assert any("неизвестный район" in error for error in unknown["errors"])


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


@pytest.mark.parametrize("district_id", [["nura"], {"id": "nura"}, [], {}, 1, False])
def test_direct_engine_rejects_invalid_district_types_without_crashing(district_id) -> None:
    selections = [{"measure_id": "M7", "district_id": district_id}, *REFERENCE_SCENARIO[1:]]

    validation = validate_choices(selections, require_five=True)

    assert validation["valid"] is False
    assert any("района должен быть строкой" in error for error in validation["errors"])
    with pytest.raises(ValueError, match="района должен быть строкой"):
        simulate(selections)


def test_clip_bounds_include_synergy_and_keep_preclip_attribution(monkeypatch) -> None:
    districts = deepcopy(DISTRICTS)
    districts["nura"]["indicators"].update({"B1": 89, "T1": 1})
    monkeypatch.setattr("backend.app.engine.DISTRICTS", districts)
    report = simulate([
        {"measure_id": "M7", "district_id": "nura"},
        {"measure_id": "M8", "district_id": "nura"},
        {"measure_id": "M10", "district_id": "nura"},
        {"measure_id": "M11", "district_id": "nura"},
        {"measure_id": "M12"},
    ])
    indicators = {
        indicator["id"]: indicator
        for district in report["districts"] if district["id"] == "nura"
        for indicator in district["indicators"]
    }

    # B1: 89 + 10.5 from M10 + 2 from synergy = 101.5, then clipped.
    assert indicators["B1"]["after"] == 100
    assert indicators["B1"]["delta"] == 11
    assert sum(item["amount"] for item in indicators["B1"]["contributions"]) == 12.5
    # T1: 1 - 1.75 from M11 is clipped at the lower boundary.
    assert indicators["T1"]["after"] == 0
    assert indicators["T1"]["delta"] == -1
    assert DISTRICTS["nura"]["indicators"]["B1"] == 55
    assert DISTRICTS["nura"]["indicators"]["T1"] == 55


def test_clip_happens_after_summing_opposing_effects_in_either_order(monkeypatch) -> None:
    districts = deepcopy(DISTRICTS)
    districts["nura"]["indicators"]["T1"] = 99
    monkeypatch.setattr("backend.app.engine.DISTRICTS", districts)
    selections = [
        {"measure_id": "M2"},
        {"measure_id": "M11", "district_id": "nura"},
        {"measure_id": "M9", "district_id": "nura"},
        {"measure_id": "M10", "district_id": "nura"},
        {"measure_id": "M12"},
    ]
    reports = [simulate(selections), simulate(list(reversed(selections)))]

    for report in reports:
        t1 = next(
            indicator
            for district in report["districts"] if district["id"] == "nura"
            for indicator in district["indicators"] if indicator["id"] == "T1"
        )
        # 99 + 3 - 1.75 = 100.25 -> 100; early clipping would produce 98.25.
        assert t1["after"] == 100
    assert reports[0]["score"] == reports[1]["score"]
