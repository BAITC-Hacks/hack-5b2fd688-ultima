from __future__ import annotations

import asyncio
import json
import re

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
            if json_body is None:
                return await client.request(method, path)
            # Escape Unicode so malformed strings reach the server, not HTTPX's encoder.
            return await client.request(
                method,
                path,
                content=json.dumps(json_body, ensure_ascii=True),
                headers={"Content-Type": "application/json"},
            )

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
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", first_entry["owner_token"])

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


@pytest.mark.parametrize(
    "team_name",
    ["", "   ", "\u001c", "\u200b", "\u0000", "Команда\n", "\ud800", "\u0301\ufe0f", "x" * 41, 42, ["Нура"]],
)
def test_invalid_team_names_are_rejected_by_api_and_store(team_name) -> None:
    response = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": team_name, "selections": REFERENCE_SCENARIO},
    )

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert "score" not in response.json()
    with pytest.raises(ValueError):
        submit_scenario(team_name, simulate(REFERENCE_SCENARIO), REFERENCE_SCENARIO)
    assert get_leaderboard() == []


def test_name_normalisation_precedes_length_check_and_is_shared_with_store() -> None:
    # The raw input exceeds 40 characters; its normalized visible name does not.
    raw_name = " " * 50 + "E\u0301quipe\u00a0\u2003 Астана  🌳  "
    normalized_name = "Équipe Астана 🌳"
    response = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": raw_name, "selections": REFERENCE_SCENARIO},
    )

    assert response.status_code == 200
    created = response.json()["entry"]
    assert created["team_name"] == normalized_name
    conflict = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": normalized_name.lower(), "selections": IMPROVED_SCENARIO},
    )
    assert conflict.status_code == 409
    updated = submit_scenario(
        raw_name,
        simulate(IMPROVED_SCENARIO),
        IMPROVED_SCENARIO,
        owner_token=created["owner_token"],
    )
    assert updated["team_name"] == normalized_name
    assert updated["score"] == pytest.approx(57.20556)
    assert len(get_leaderboard()) == 1


@pytest.mark.parametrize(
    "owner_token",
    [
        "", "a" * 19, "a" * 101, "a" * 31 + "+", "a" * 31 + "/", "a" * 31 + "=",
        "a" * 31 + "\n", "a" * 31 + "я", "a" * 31 + "\ud800", "a" * 31 + "\u200b",
        123, ["a" * 32],
    ],
)
def test_invalid_owner_tokens_are_rejected_before_storage(owner_token) -> None:
    report = simulate(REFERENCE_SCENARIO)
    submit_scenario("Owner", report, REFERENCE_SCENARIO)
    response = request(
        "POST",
        "/api/leaderboard",
        json_body={
            "team_name": "Owner",
            "owner_token": owner_token,
            "selections": IMPROVED_SCENARIO,
        },
    )

    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    with pytest.raises(ValueError, match="Код команды"):
        submit_scenario("Owner", report, REFERENCE_SCENARIO, owner_token=owner_token)
    with pytest.raises(ValueError, match="Код команды"):
        submit_scenario("New owner", report, REFERENCE_SCENARIO, owner_token=owner_token)
    entries = get_leaderboard()
    assert len(entries) == 1
    assert entries[0]["score"] == pytest.approx(56.54307)


def test_well_formed_but_incorrect_owner_token_is_a_conflict() -> None:
    submit_scenario("Owner", simulate(REFERENCE_SCENARIO), REFERENCE_SCENARIO)
    response = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": "Owner", "owner_token": "_" * 32, "selections": IMPROVED_SCENARIO},
    )

    assert response.status_code == 409
    assert get_leaderboard()[0]["score"] == pytest.approx(56.54307)


def test_invalid_unicode_in_extra_field_has_a_serializable_validation_error() -> None:
    response = request(
        "POST",
        "/api/leaderboard",
        json_body={"team_name": "Owner", "selections": REFERENCE_SCENARIO, "\ud800": "extra"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] in {"string_unicode", "extra_forbidden"}
    assert get_leaderboard() == []
