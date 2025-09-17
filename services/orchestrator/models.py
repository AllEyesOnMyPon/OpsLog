from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StartRequest(BaseModel):
    # Sposób wskazania scenariusza (jeden z):
    name: str | None = Field(
        None, description="Nazwa scenariusza z katalogu 'scenarios/'. Szukamy *.yaml|*.yml."
    )
    yaml_path: str | None = Field(
        None, description="Ścieżka do pliku YAML scenariusza (relative lub absolute)."
    )
    inline: dict[str, Any] | None = Field(
        None, description="Scenariusz w postaci słownika (z kluczem 'emitters' itd.)."
    )

    # Opcje runnera:
    seed: int | None = None
    dry_run: bool = False
    debug: bool = False
    strict: bool = False
    step_timeout_sec: float = 20.0
    py: str | None = None  # interpreter; domyślnie sys.executable

    # Dodatkowe ENVy dla procesu scenariusza:
    env_overrides: dict[str, str] = Field(default_factory=dict)


class StartResponse(BaseModel):
    scenario_id: str
    status: str
    name: str
    log_file: str


class StopRequest(BaseModel):
    scenario_id: str


class ScenarioInfo(BaseModel):
    scenario_id: str
    name: str
    status: str  # running|finished|stopped|error
    pid: int | None = None
    started_at: float
    updated_at: float
    log_file: str | None = None
    scenario_path: str | None = None
    dry_run: bool = False
    debug: bool = False
    seed: int | None = None
    strict: bool = False
    step_timeout_sec: float = 20.0


class ListResponse(BaseModel):
    items: list[ScenarioInfo]
