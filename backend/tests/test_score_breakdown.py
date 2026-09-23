import pytest

from backend.app.engine import baseline_report, public_config, simulate


def test_example_is_a_valid_canonical_plan() -> None:
    example = public_config()["example_scenario"]
    report = simulate(example["selections"])
    assert len(example["selections"]) == 5
    assert example["total_cost"] == report["total_cost"] == 95
    assert example["score"] == pytest.approx(56.54307)
    assert report["critical_count"] == 0
    assert {item["measure_id"] for item in example["rationale"]} == {
        item["measure_id"] for item in example["selections"]
    }


@pytest.mark.parametrize("use_example", [True, False])
def test_score_components_reconcile_before_after_and_exact_delta(use_example) -> None:
    report = simulate(public_config()["example_scenario"]["selections"]) if use_example else baseline_report()
    components = report["score_breakdown"]["components"]
    assert sum(item["before"]["contribution"] for item in components) == pytest.approx(report["baseline_score"])
    assert sum(item["after"]["contribution"] for item in components) == pytest.approx(report["score"])
    assert sum(item["delta"] for item in components) == pytest.approx(report["score_delta"])
    critical = next(item for item in components if item["id"] == "critical")
    assert critical["before"]["contribution"] == -2
    assert critical["after"]["contribution"] == (0 if use_example else -2)


def test_weakest_component_tracks_a_different_district_after_the_plan() -> None:
    report = simulate([
        {"measure_id": measure_id, "district_id": "nura"}
        for measure_id in ("M3", "M7", "M8", "M10", "M11")
    ])
    weakest = next(item for item in report["score_breakdown"]["components"] if item["id"] == "weakest")
    assert weakest["before"]["district_name"] == "Нура"
    assert weakest["after"]["district_name"] == "Сарыарка"
    assert weakest["before"]["contribution"] == pytest.approx(0.3 * 49.18)
    assert weakest["after"]["contribution"] == pytest.approx(0.3 * 54.65)
