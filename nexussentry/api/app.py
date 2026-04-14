"""FastAPI application for the NexusSentry backend."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .models import (
    ArtifactsResponse,
    CreateRunRequest,
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

    @app.get("/api/v1/runs/{run_id}/stream")
    async def stream_events_endpoint(
        run_id: str,
        request: Request,
        cursor: int = 0,
        poll_interval_ms: int = 1000,
    ):
        app.state.run_service.get_run(run_id)
        poll_seconds = max(0.1, poll_interval_ms / 1000)

        async def event_stream():
            next_cursor = max(0, cursor)
            terminal_statuses = {"completed", "failed", "stopped"}

            while True:
                if await request.is_disconnected():
                    break

                batch = app.state.run_service.list_events(run_id, cursor=next_cursor, limit=200)
                for item in batch["events"]:
                    payload = json.dumps(item, separators=(",", ":"), default=str)
                    yield f"event: run_event\ndata: {payload}\n\n"

                next_cursor = batch["next_cursor"]
                run = app.state.run_service.get_run(run_id)
                if run["status"] in terminal_statuses and next_cursor >= batch["total"]:
                    summary = json.dumps(
                        {
                            "run_id": run_id,
                            "status": run["status"],
                            "completed_at": run.get("completed_at"),
                        },
                        separators=(",", ":"),
                        default=str,
                    )
                    yield f"event: run_completed\ndata: {summary}\n\n"
                    break

                if not batch["events"]:
                    yield ": keepalive\n\n"

                await asyncio.sleep(poll_seconds)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

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
