"""HTTP API and static web app for the city simulator."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .ai import explain
from .engine import baseline_report, public_config, simulate, validate_choices
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


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
