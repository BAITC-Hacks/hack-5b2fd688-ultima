"""HTTP API and static web app for the city simulator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from .ai import explain
from .engine import DATA, public_config, simulate, validate_choices
from .leaderboard import (
    TeamNameTakenError,
    get_leaderboard,
    normalise_team_name,
    submit_scenario,
    validate_owner_token,
)
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


TeamName = Annotated[str, BeforeValidator(normalise_team_name)]
OwnerToken = Annotated[str | None, BeforeValidator(validate_owner_token)]


class TeamSubmissionRequest(SelectionRequest):
    team_name: TeamName
    owner_token: OwnerToken = None


app = FastAPI(
    title="Аким на 5 часов — симулятор",
    description="Симулятор распределения синтетического городского бюджета.",
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def request_validation_error(_request: Request, error: RequestValidationError) -> Response:
    # Do not echo raw values (including edit tokens). JSON escaping also keeps
    # invalid Unicode in request field names from breaking the error response.
    details = [
        {key: item[key] for key in ("type", "loc", "msg")}
        for item in error.errors()
    ]
    return Response(
        content=json.dumps({"detail": details}, ensure_ascii=True),
        status_code=422,
        media_type="application/json",
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
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"valid": True, "model_version": report["model_version"], "entry": entry}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
