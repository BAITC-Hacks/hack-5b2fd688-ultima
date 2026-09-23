"""HTTP API and static web app for the city simulator."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .ai import explain
from .engine import DATA, public_config, simulate, validate_choices
from .leaderboard import TeamNameTakenError, get_leaderboard, submit_scenario
from .recommender import recommend_alternatives

ROOT_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT_DIR / "web"
load_dotenv(ROOT_DIR / ".env")


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure_id: str = Field(min_length=2, max_length=3)
    district_id: str | None = Field(default=None, max_length=32)


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selections: list[Selection] = Field(default_factory=list, max_length=10)


TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class TeamSubmissionRequest(SelectionRequest):
    team_name: TeamName
    owner_token: str | None = Field(default=None, min_length=20, max_length=100)


app = FastAPI(
    title="Аким на 5 часов — симулятор",
    description="Симулятор распределения синтетического городского бюджета.",
    version="1.0.0",
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return public_config()


@app.post("/api/validate")
def validate_selection(request: SelectionRequest) -> dict[str, Any]:
    return validate_choices(request.selections)


@app.post("/api/simulate")
def run_simulation(request: SelectionRequest) -> Any:
    validation = validate_choices(request.selections, require_five=True)
    if not validation["valid"]:
        return JSONResponse(status_code=422, content={"valid": False, **validation})
    return {"valid": True, **simulate(request.selections)}


@app.post("/api/analyze")
def analyze_scenario(request: SelectionRequest) -> Any:
    validation = validate_choices(request.selections, require_five=True)
    if not validation["valid"]:
        return JSONResponse(status_code=422, content={"valid": False, **validation})
    report = simulate(request.selections)
    recommendations = recommend_alternatives(request.selections, current_report=report)
    return {
        "valid": True,
        **report,
        "alternative_scenarios": recommendations["alternatives"],
        "recommendation_message": recommendations["message"],
        "explanation": explain(report, recommendations["alternatives"]),
    }


@app.get("/api/leaderboard")
def leaderboard() -> dict[str, Any]:
    return {
        "model_version": DATA["model_version"],
        "entries": get_leaderboard(),
    }


@app.post("/api/leaderboard")
def submit_leaderboard_entry(request: TeamSubmissionRequest) -> Any:
    validation = validate_choices(request.selections, require_five=True)
    if not validation["valid"]:
        return JSONResponse(status_code=422, content={"valid": False, **validation})
    report = simulate(request.selections)
    try:
        entry = submit_scenario(
            request.team_name,
            report,
            [selection.model_dump() for selection in request.selections],
            owner_token=request.owner_token,
        )
    except TeamNameTakenError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"valid": True, "model_version": report["model_version"], "entry": entry}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
