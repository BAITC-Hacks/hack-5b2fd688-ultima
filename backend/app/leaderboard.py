"""Shared, persistent comparison of team scenarios."""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from .engine import DATA

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "scenarios.sqlite3"


class TeamNameTakenError(Exception):
    """A different owner already registered this team name."""


def normalise_team_name(team_name: str) -> str:
    """Apply the same canonical name and validation for HTTP and direct callers."""
    if not isinstance(team_name, str):
        raise ValueError("Имя команды должно быть строкой.")  # noqa: TRY004 - shared Pydantic validation contract
    # Check before splitting: Python treats some control characters as whitespace.
    if any(
        not character.isprintable() and unicodedata.category(character) != "Zs"
        for character in team_name
    ):
        raise ValueError("Имя команды не должно содержать управляющие или невидимые символы.")
    normalized = " ".join(unicodedata.normalize("NFC", team_name).split())
    if not 1 <= len(normalized) <= 40:
        raise ValueError("Имя команды должно содержать от 1 до 40 символов после нормализации.")
    if not any(unicodedata.category(character)[0] in "LNPS" for character in normalized):
        raise ValueError("Имя команды должно содержать видимые символы.")
    return normalized


def validate_owner_token(owner_token: str | None) -> str | None:
    """Accept only the URL-safe alphabet used by token_urlsafe, or no token."""
    if owner_token is not None and (
        not isinstance(owner_token, str)
        or re.fullmatch(r"[A-Za-z0-9_-]{20,100}", owner_token) is None
    ):
        raise ValueError("Код команды должен содержать от 20 до 100 символов: A–Z, a–z, 0–9, _ или -.")
    return owner_token


def _database_path() -> Path:
    return Path(os.getenv("SIMULATOR_DB_PATH", str(DEFAULT_DB))).expanduser()


def _connect() -> sqlite3.Connection:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS scenario_submissions (
            team_key TEXT PRIMARY KEY,
            team_name TEXT NOT NULL,
            owner_token_hash TEXT NOT NULL,
            model_version TEXT NOT NULL,
            score REAL NOT NULL,
            baseline_score REAL NOT NULL,
            score_delta REAL NOT NULL,
            display_score_delta REAL NOT NULL,
            total_cost INTEGER NOT NULL,
            budget_remaining INTEGER NOT NULL,
            critical_count INTEGER NOT NULL,
            weakest_district_id TEXT NOT NULL,
            weakest_district_name TEXT NOT NULL,
            district_scores_json TEXT NOT NULL,
            selections_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_scenario_submissions_rank
        ON scenario_submissions (model_version, score DESC, total_cost ASC)
        """
    )
    return connection


def submit_scenario(
    team_name: str,
    report: dict[str, Any],
    selections: list[dict[str, Any]],
    *,
    owner_token: str | None = None,
) -> dict[str, Any]:
    """Insert/update one team row, guarded by its private per-team edit token."""
    normalized_name = normalise_team_name(team_name)
    owner_token = validate_owner_token(owner_token)
    team_key = normalized_name.casefold()
    district_scores = {
        district["id"]: district["score_after"] for district in report["districts"]
    }
    selections_json = json.dumps(
        sorted(
            (
                {"measure_id": choice["measure_id"], "district_id": choice.get("district_id")}
                for choice in selections
            ),
            key=lambda choice: (choice["measure_id"], choice["district_id"] or ""),
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    issued_token: str | None = None

    with closing(_connect()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT owner_token_hash FROM scenario_submissions WHERE team_key = ?", (team_key,)
        ).fetchone()
        if existing is None:
            issued_token = secrets.token_urlsafe(24)
            token_hash = sha256(issued_token.encode("utf-8")).hexdigest()
        elif not owner_token or not secrets.compare_digest(
            existing["owner_token_hash"], sha256(owner_token.encode("utf-8")).hexdigest()
        ):
            raise TeamNameTakenError("Имя команды уже занято. Выберите другое имя или используйте свой код команды.")
        else:
            token_hash = existing["owner_token_hash"]

        connection.execute(
            """
            INSERT INTO scenario_submissions (
                team_key, team_name, owner_token_hash, model_version, score,
                baseline_score, score_delta, display_score_delta, total_cost,
                budget_remaining, critical_count, weakest_district_id,
                weakest_district_name, district_scores_json, selections_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(team_key) DO UPDATE SET
                team_name = excluded.team_name,
                model_version = excluded.model_version,
                score = excluded.score,
                baseline_score = excluded.baseline_score,
                score_delta = excluded.score_delta,
                display_score_delta = excluded.display_score_delta,
                total_cost = excluded.total_cost,
                budget_remaining = excluded.budget_remaining,
                critical_count = excluded.critical_count,
                weakest_district_id = excluded.weakest_district_id,
                weakest_district_name = excluded.weakest_district_name,
                district_scores_json = excluded.district_scores_json,
                selections_json = excluded.selections_json,
                updated_at = excluded.updated_at
            """,
            (
                team_key,
                normalized_name,
                token_hash,
                report["model_version"],
                report["score"],
                report["baseline_score"],
                report["score_delta"],
                report["display_score_delta"],
                report["total_cost"],
                report["budget_remaining"],
                report["critical_count"],
                report["weakest_district_id"],
                report["weakest_district_name"],
                json.dumps(district_scores, ensure_ascii=False, separators=(",", ":")),
                selections_json,
                updated_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM scenario_submissions WHERE team_key = ?", (team_key,)
        ).fetchone()

    return {**_public_row(row), "owner_token": issued_token}


def _public_row(row: sqlite3.Row, rank: int | None = None) -> dict[str, Any]:
    return {
        "rank": rank,
        "team_name": row["team_name"],
        "model_version": row["model_version"],
        "score": row["score"],
        "baseline_score": row["baseline_score"],
        "score_delta": row["score_delta"],
        "display_score_delta": row["display_score_delta"],
        "total_cost": row["total_cost"],
        "budget_remaining": row["budget_remaining"],
        "critical_count": row["critical_count"],
        "weakest_district_id": row["weakest_district_id"],
        "weakest_district_name": row["weakest_district_name"],
        "district_scores": json.loads(row["district_scores_json"]),
        "selections": json.loads(row["selections_json"]),
        "updated_at": row["updated_at"],
    }


def get_leaderboard(*, limit: int = 50, model_version: str | None = None) -> list[dict[str, Any]]:
    """Return a fair comparison set for one shared version of the model."""
    current_version = model_version or DATA["model_version"]
    with closing(_connect()) as connection:
        rows = connection.execute(
            """
            SELECT * FROM scenario_submissions
            WHERE model_version = ?
            ORDER BY score DESC, critical_count ASC, total_cost ASC,
                     updated_at ASC, team_name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (current_version, limit),
        ).fetchall()
    return [_public_row(row, rank=index) for index, row in enumerate(rows, start=1)]
