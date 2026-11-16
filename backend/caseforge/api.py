"""HTTP API. A thin shell over RunService; no simulation logic lives here."""

from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Path as UrlPath, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .engine import EngineError, PolicyFactory
from .policies import make_policy
from .policies.llm import PROCESS_BUDGET
from .lab import ChallengeError
from .lab_service import LabService
from .netguard import LocalRequestGuard, allowed_hosts as resolve_allowed_hosts, hosts_from_env
from .service import BadRequest, NotFound, RunService
from .store import Store, StoreError

DEFAULT_DB = "caseforge.sqlite3"


class CreateRunBody(BaseModel):
    scenario_id: str = "missing_prototype"
    seed: int = Field(default=7, ge=0, le=2**31 - 1)
    policies: dict[str, str] = Field(default_factory=dict)
    label: str = Field(default="", max_length=80)


class StepBody(BaseModel):
    ticks: int = Field(default=1, ge=1, le=100)


class InterventionBody(BaseModel):
    intervention_id: str


class PolicyBody(BaseModel):
    agent: str
    policy: str


class BranchBody(BaseModel):
    tick: int = Field(ge=0)
    label: str = Field(default="", max_length=80)


class LabExecuteBody(BaseModel):
    seeds: list[int] = Field(default_factory=list, max_length=100)
    replay: bool = False


class LabOpenBody(BaseModel):
    seed: int = Field(default=0, ge=0, le=2**31 - 1)


# A challenge id names an entry of the fixed manifest and is one path segment: lowercase letters, digits and
# underscores. Anything else is refused before the lookup, so a crafted id can never reach it.
ChallengeId = Annotated[str, UrlPath(pattern=r"^[a-z0-9_]{1,64}$", description="a registered challenge id")]


def frontend_dist() -> Path | None:
    override = os.environ.get("CASEFORGE_FRONTEND_DIST")
    candidate = Path(override) if override else Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def create_app(
    db_path: str | os.PathLike | None = None,
    policy_factory: PolicyFactory = make_policy,
    lab_service: LabService | None = None,
    allowed_hosts: Iterable[str] | None = None,
) -> FastAPI:
    """`allowed_hosts` names hosts to answer to besides localhost, 127.0.0.1 and ::1
    (default: `CASEFORGE_ALLOWED_HOSTS`, comma separated). See `netguard.py`."""
    path = str(db_path) if db_path is not None else os.environ.get("CASEFORGE_DB", DEFAULT_DB)
    service = RunService(Store(path), policy_factory)
    app = FastAPI(title="CaseForge", version=__version__)
    app.state.service = service
    app.state.lab = lab_service or LabService()
    extra = list(allowed_hosts) if allowed_hosts is not None else hosts_from_env(os.environ.get("CASEFORGE_ALLOWED_HOSTS"))
    app.add_middleware(LocalRequestGuard, allowed=resolve_allowed_hosts(None, extra))

    @app.exception_handler(NotFound)
    async def _not_found(_, exc: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(EngineError)
    async def _conflict(_, exc: EngineError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ChallengeError)
    async def _lab_refused(_, exc: ChallengeError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(BadRequest)
    async def _bad_request(_, exc: BadRequest):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(StoreError)
    async def _store_error(_, exc: StoreError):
        return JSONResponse(status_code=500, content={"detail": f"storage error: {exc}"})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "llm_calls_used": PROCESS_BUDGET.spent}

    @app.get("/api/scenarios")
    def scenarios() -> list[dict[str, Any]]:
        return service.scenarios()

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, Any]]:
        return service.list_runs()

    @app.post("/api/runs", status_code=201)
    def create_run(body: CreateRunBody) -> dict[str, Any]:
        return service.create_run(body.scenario_id, body.seed, body.policies, body.label)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return service.summary(run_id)

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(run_id: str) -> None:
        service.delete(run_id)

    @app.post("/api/runs/{run_id}/step")
    def step(run_id: str, body: StepBody) -> dict[str, Any]:
        events = service.step(run_id, body.ticks)
        return {"run": service.summary(run_id), "events": events}

    @app.post("/api/runs/{run_id}/interventions")
    def intervene(run_id: str, body: InterventionBody) -> dict[str, Any]:
        events = service.intervene(run_id, body.intervention_id)
        return {"run": service.summary(run_id), "events": events}

    @app.post("/api/runs/{run_id}/policy")
    def set_policy(run_id: str, body: PolicyBody) -> dict[str, Any]:
        events = service.set_policy(run_id, body.agent, body.policy)
        return {"run": service.summary(run_id), "events": events}

    @app.post("/api/runs/{run_id}/branch", status_code=201)
    def branch(run_id: str, body: BranchBody) -> dict[str, Any]:
        return service.branch(run_id, body.tick, body.label)

    @app.post("/api/runs/{run_id}/reveal")
    def reveal(run_id: str) -> dict[str, Any]:
        return service.reveal(run_id)

    @app.get("/api/runs/{run_id}/snapshot")
    def get_snapshot(run_id: str, tick: int | None = Query(default=None, ge=0)) -> dict[str, Any]:
        return service.snapshot(run_id, tick)

    @app.get("/api/runs/{run_id}/events")
    def get_events(run_id: str, after: int = -1, upto_tick: int | None = Query(default=None, ge=0)) -> list[dict[str, Any]]:
        return service.events(run_id, after, upto_tick)

    @app.get("/api/runs/{run_id}/graph")
    def get_graph(run_id: str, tick: int | None = Query(default=None, ge=0), perspective: str = "all") -> dict[str, Any]:
        return service.graph(run_id, tick, perspective)

    @app.get("/api/runs/{run_id}/evaluation")
    def get_evaluation(run_id: str) -> dict[str, Any]:
        return service.evaluation(run_id)

    @app.get("/api/runs/{run_id}/verify")
    def verify(run_id: str) -> dict[str, Any]:
        return service.verify(run_id)

    @app.get("/api/compare")
    def compare(a: str, b: str) -> dict[str, Any]:
        return service.compare(a, b)

    # -- the counterfactual laboratory ------------------------------------------------------
    # Reading never runs anything. `execute` is the only route that does, and it is bounded.

    @app.get("/api/lab")
    def lab_overview() -> dict[str, Any]:
        return app.state.lab.overview()

    @app.get("/api/lab/challenges/{challenge_id}")
    def lab_challenge(challenge_id: ChallengeId, reveal: bool = False) -> dict[str, Any]:
        return app.state.lab.challenge_detail(challenge_id, reveal)

    @app.post("/api/lab/challenges/{challenge_id}/execute")
    def lab_execute(challenge_id: ChallengeId, body: LabExecuteBody, reveal: bool = False) -> dict[str, Any]:
        return app.state.lab.execute(challenge_id, body.seeds, body.replay, reveal)

    @app.post("/api/lab/challenges/{challenge_id}/open", status_code=201)
    def lab_open(challenge_id: ChallengeId, body: LabOpenBody) -> dict[str, Any]:
        request = app.state.lab.open_request(challenge_id, body.seed)
        run = service.create_run(request["scenario_id"], request["seed"], request["policies"], request["label"])
        return {"run": run, "registered_interventions": request["registered_interventions"]}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
    def unknown_api(rest: str) -> None:
        raise HTTPException(status_code=404, detail=f"no such endpoint: /api/{rest}")

    dist = frontend_dist()
    if dist is not None:
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        def no_frontend() -> dict[str, str]:
            return {"detail": "The web interface has not been built. Run `npm install` and `npm run build` in frontend/, or use /docs for the API."}

    return app
