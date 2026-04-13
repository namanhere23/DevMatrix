"""FastAPI application for the NexusSentry backend."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .models import (
    ArtifactsResponse,
    CreateRunRequest,
    DecisionRequest,
    ErrorResponse,
    EventsResponse,
    HealthResponse,
    RunResponse,
)
from .service import RunService


def _error_body(detail):
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return {"error": detail}
    return {"error": {"code": "http_error", "message": str(detail)}}


def create_app(service: RunService | None = None) -> FastAPI:
    app = FastAPI(
        title="NexusSentry Backend API",
        version="1.0.0",
        default_response_class=JSONResponse,
    )
    app.state.run_service = service or RunService()

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error."}},
        )

    @app.post("/api/v1/runs", response_model=RunResponse, responses={400: {"model": ErrorResponse}})
    async def create_run_endpoint(
        request: CreateRunRequest,
        idempotency_key: str | None = Header(default=None),
    ):
        return app.state.run_service.create_run(
            request.goal,
            request.engine,
            idempotency_key=idempotency_key,
        )

    @app.get("/api/v1/runs/{run_id}", response_model=RunResponse, responses={404: {"model": ErrorResponse}})
    async def get_run_endpoint(run_id: str):
        return app.state.run_service.get_run(run_id)

    @app.get("/api/v1/runs/{run_id}/events", response_model=EventsResponse)
    async def get_events_endpoint(run_id: str, cursor: int = 0, limit: int = 200):
        return app.state.run_service.list_events(run_id, cursor=cursor, limit=limit)

    @app.post(
        "/api/v1/runs/{run_id}/decision",
        response_model=RunResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    async def post_decision_endpoint(
        run_id: str,
        decision: DecisionRequest,
        idempotency_key: str | None = Header(default=None),
    ):
        return app.state.run_service.submit_decision(
            run_id,
            decision.action,
            actor=decision.actor or "ui",
            reason=decision.reason,
            idempotency_key=idempotency_key,
        )

    @app.get("/api/v1/runs/{run_id}/artifacts", response_model=ArtifactsResponse)
    async def get_artifacts_endpoint(run_id: str):
        return app.state.run_service.list_artifacts(run_id)

    @app.get("/api/v1/runs/{run_id}/artifacts/{artifact_id}")
    async def download_artifact_endpoint(run_id: str, artifact_id: str):
        path = app.state.run_service.get_artifact_path(run_id, artifact_id)
        return FileResponse(path)

    @app.get("/api/v1/health/live", response_model=HealthResponse)
    async def live_endpoint():
        return app.state.run_service.health_live()

    @app.get("/api/v1/health/ready", response_model=HealthResponse)
    async def ready_endpoint():
        return app.state.run_service.health_ready()

    return app
