from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.app.engine import simulate
from backend.app.leaderboard import get_leaderboard, submit_scenario
from backend.app.main import app

REFERENCE_SCENARIO = [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12", "district_id": None},
    {"measure_id": "M5", "district_id": "saryarka"},
]
IMPROVED_SCENARIO = [
    *REFERENCE_SCENARIO[:4],
    {"measure_id": "M3", "district_id": "nura"},
]


def request(method: str, path: str, *, json_body=None) -> httpx.Response:
    async def send() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.request(method, path, json=json_body)

    return asyncio.run(send())


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMULATOR_DB_PATH", str(tmp_path / "scenarios.sqlite3"))


def test_teams_share_baseline_but_keep_distinct_ranked_scenarios() -> None:
    empty = request("GET", "/api/leaderboard").json()
    assert empty["entries"] == []

    first = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": "Ultima", "selections": REFERENCE_SCENARIO},
    )
    second = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": "Новый город", "selections": IMPROVED_SCENARIO},
    )

    assert first.status_code == second.status_code == 200
    first_entry, second_entry = first.json()["entry"], second.json()["entry"]
    assert first_entry["score"] == pytest.approx(56.54307)
    assert second_entry["score"] == pytest.approx(57.20556)
    assert first_entry["baseline_score"] == second_entry["baseline_score"] == pytest.approx(
        52.55768
    )
    assert len(first_entry["owner_token"]) >= 20

    shared = request("GET", "/api/leaderboard").json()["entries"]
    assert [entry["team_name"] for entry in shared] == ["Новый город", "Ultima"]
    assert [entry["rank"] for entry in shared] == [1, 2]
    assert all("owner_token" not in entry for entry in shared)
    assert [entry["total_cost"] for entry in shared] == [100, 95]
    assert shared[0]["district_scores"]["nura"] != shared[1]["district_scores"]["nura"]


def test_team_name_is_reserved_and_only_its_owner_can_update() -> None:
    created = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": "  Ultima  ", "selections": REFERENCE_SCENARIO},
    )
    token = created.json()["entry"]["owner_token"]

    conflict = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": "ultima", "selections": IMPROVED_SCENARIO},
    )
    assert conflict.status_code == 409
    assert "занято" in conflict.json()["detail"]

    updated = request(
        "POST",
        "/api/leaderboard",
        json_body={
            "team_name": "Ultima",
            "owner_token": token,
            "selections": IMPROVED_SCENARIO,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["entry"]["score"] == pytest.approx(57.20556)
    assert updated.json()["entry"]["owner_token"] is None
    assert len(request("GET", "/api/leaderboard").json()["entries"]) == 1


def test_invalid_scenario_never_appears_in_leaderboard() -> None:
    invalid = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": "Invalid", "selections": REFERENCE_SCENARIO[:4]},
    )
    assert invalid.status_code == 422
    assert "score" not in invalid.json()
    assert request("GET", "/api/leaderboard").json()["entries"] == []


def test_old_model_versions_are_not_mixed_into_current_rankings() -> None:
    older_report = {**simulate(REFERENCE_SCENARIO), "model_version": "old-model"}
    submit_scenario("Archived", older_report, REFERENCE_SCENARIO)

    assert get_leaderboard() == []
    assert [entry["team_name"] for entry in get_leaderboard(model_version="old-model")] == [
        "Archived"
    ]
