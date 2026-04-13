# api_server.py
"""
╔═══════════════════════════════════════════════════════════╗
║       NexusSentry v3.0 — FastAPI Server                   ║
║                                                           ║
║  Wraps the run_swarm() pipeline behind a REST API with    ║
║  real-time SSE streaming of agent logs.                   ║
║                                                           ║
║  Usage:                                                   ║
║    python api_server.py                                   ║
║    uvicorn api_server:app --reload                        ║
╚═══════════════════════════════════════════════════════════╝
"""

import asyncio
import io
import json
import os
import sys
import time
import uuid
import logging
import threading
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from typing import Optional

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# ── App Setup ──
app = FastAPI(
    title="NexusSentry API",
    description="Multi-Agent Orchestration API with real-time streaming",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Configuration ──
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# ── State Tracking ──
active_runs: dict[str, dict] = {}


# ── Request/Response Models ──
class RunRequest(BaseModel):
    goal: str


class OptimizeRequest(BaseModel):
    prompt: str


class RunStatus(BaseModel):
    run_id: str
    status: str
    goal: str


# ── Streaming Log Capture ──
class LogCapture(io.StringIO):
    """Captures print() output and feeds it into an async queue."""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._queue = queue
        self._loop = loop
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text or text == "\n":
            return len(text) if text else 0
        self._buffer += text
        # Flush on newlines
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                try:
                    self._loop.call_soon_threadsafe(
                        self._queue.put_nowait,
                        {"type": "log", "data": line, "timestamp": time.time()},
                    )
                except Exception:
                    pass
        return len(text)

    def flush(self):
        if self._buffer.strip():
            try:
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait,
                    {"type": "log", "data": self._buffer.strip(), "timestamp": time.time()},
                )
            except Exception:
                pass
            self._buffer = ""


# ── Logging Handler for SSE ──
class QueueLoggingHandler(logging.Handler):
    """Sends log records to the SSE queue."""

    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._queue = queue
        self._loop = loop

    def emit(self, record):
        try:
            msg = self.format(record)
            if msg.strip():
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait,
                    {"type": "log", "data": msg.strip(), "timestamp": time.time()},
                )
        except Exception:
            pass


# ── API Endpoints ──

# ── Mount static assets from Vite build ──
_dist_dir = FRONTEND_DIR / "dist"
_assets_dir = _dist_dir / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the frontend HTML (Vite build output or fallback to raw index.html)."""
    # Try Vite build output first
    dist_index = FRONTEND_DIR / "dist" / "index.html"
    if dist_index.exists():
        return HTMLResponse(content=dist_index.read_text(encoding="utf-8"))
    # Fallback to raw index.html (for non-React setups)
    html_path = FRONTEND_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Frontend not found. Run 'npm run build' in frontend/</h1>", status_code=404)


@app.get("/api/health")
async def health_check():
    """System health and readiness check."""
    health = {
        "status": "ok",
        "version": "3.0.0",
        "active_runs": len(active_runs),
    }

    # Check providers
    try:
        from nexussentry.providers.llm_provider import get_provider
        provider = get_provider()
        health["providers"] = provider.available_providers
        health["mock_mode"] = provider.mock_mode
    except Exception as e:
        health["providers"] = []
        health["mock_mode"] = True
        health["provider_error"] = str(e)

    # Check agents
    try:
        from nexussentry.agents.scout import ScoutAgent
        from nexussentry.agents.architect import ArchitectAgent
        from nexussentry.agents.builder import BuilderAgent
        health["agents_available"] = True
    except ImportError:
        health["agents_available"] = False

    return health


@app.post("/api/run")
async def run_swarm_endpoint(request: RunRequest):
    """
    Execute a NexusSentry swarm run.
    Returns SSE stream of real-time events + final results.
    """
    goal = request.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="Goal cannot be empty")

    if len(active_runs) >= 2:
        raise HTTPException(
            status_code=429,
            detail="Too many active runs. Please wait for current runs to complete.",
        )

    run_id = str(uuid.uuid4())[:8]
    loop = asyncio.get_event_loop()
    event_queue: asyncio.Queue = asyncio.Queue()

    active_runs[run_id] = {"status": "running", "goal": goal, "started": time.time()}

    async def event_generator():
        """SSE generator that yields events from the swarm run."""
        # Send initial event
        yield f"data: {json.dumps({'type': 'start', 'run_id': run_id, 'goal': goal})}\n\n"

        # Start the swarm in a background thread
        result_holder = {"result": None, "error": None}

        def _run_swarm_sync():
            """Run the swarm synchronously in a thread, capturing output."""
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            log_capture = LogCapture(event_queue, loop)

            # Add logging handler to capture logging output too
            queue_handler = QueueLoggingHandler(event_queue, loop)
            queue_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S"))
            root_logger = logging.getLogger()
            root_logger.addHandler(queue_handler)

            try:
                sys.stdout = log_capture
                sys.stderr = log_capture

                from nexussentry.main import run_swarm
                result = asyncio.run(run_swarm(goal, enable_dashboard=False, slow=False))
                result_holder["result"] = result
            except Exception as e:
                result_holder["error"] = str(e)
                import traceback
                result_holder["traceback"] = traceback.format_exc()
            finally:
                sys.stdout = original_stdout
                sys.stderr = original_stderr
                root_logger.removeHandler(queue_handler)
                log_capture.flush()
                # Signal completion
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    {"type": "__done__"},
                )

        thread = threading.Thread(target=_run_swarm_sync, daemon=True)
        thread.start()

        # Stream events from the queue
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()})}\n\n"
                continue

            if event.get("type") == "__done__":
                break

            # Clean ANSI escape codes for frontend display
            if "data" in event:
                event["data"] = _strip_ansi(event["data"])

            yield f"data: {json.dumps(event, default=str)}\n\n"

        # Wait for thread to finish
        thread.join(timeout=5)

        # Send final result
        if result_holder["error"]:
            final_event = {
                "type": "error",
                "error": result_holder["error"],
                "traceback": result_holder.get("traceback", ""),
            }
        else:
            results = result_holder["result"] or []

            # Find the session output directory
            session_dir = _find_latest_session_dir()
            session_id = session_dir.name if session_dir else None

            # Read generated artifacts
            artifacts = {}
            if session_dir:
                # Try max_output first, fallback to final
                primary_dir = session_dir / "max_output"
                fallback_dir = session_dir / "final"
                
                target_dir = primary_dir if primary_dir.exists() else fallback_dir
                
                if target_dir.exists():
                    for f in target_dir.iterdir():
                        if f.is_file():
                            try:
                                artifacts[f.name] = f.read_text(encoding="utf-8")
                            except Exception:
                                artifacts[f.name] = "[Binary file]"

            # Build scorecard
            done = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "done")
            failed = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "failed")
            valid_scores = [
                r.get("score", 0)
                for r in results
                if isinstance(r, dict) and isinstance(r.get("score"), (int, float))
            ]
            avg_score = sum(valid_scores) / max(1, len(valid_scores)) if valid_scores else 0

            final_event = {
                "type": "complete",
                "run_id": run_id,
                "session_id": session_id,
                "scorecard": {
                    "total_tasks": len(results),
                    "completed": done,
                    "failed": failed,
                    "avg_score": round(avg_score, 1),
                },
                "tasks": [
                    {
                        "task_id": r.get("task_id"),
                        "task": r.get("task", ""),
                        "status": r.get("status", "unknown"),
                        "score": r.get("score", 0),
                        "attempts": r.get("attempts", 0),
                        "execution_mode": r.get("execution_mode", "unknown"),
                    }
                    for r in results
                    if isinstance(r, dict)
                ],
                "artifacts": artifacts,
            }

        active_runs.pop(run_id, None)
        yield f"data: {json.dumps(final_event, default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/optimize")
async def optimize_prompt_endpoint(request: OptimizeRequest):
    """Optimize a raw user prompt before dispatching it to the swarm."""
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    try:
        from nexussentry.agents.optimizer import OptimizerAgent

        optimizer = OptimizerAgent()
        result = optimizer.optimize(prompt)
        return {
            "status": "ok",
            "result": result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prompt optimization failed: {e}")


@app.get("/api/sessions")
async def list_sessions():
    """List all past session directories."""
    sessions = []
    if OUTPUT_DIR.exists():
        for session_dir in sorted(OUTPUT_DIR.iterdir(), reverse=True):
            if session_dir.is_dir() and session_dir.name.startswith("session_"):
                manifest_path = session_dir / "manifest.json"
                session_info = {
                    "session_id": session_dir.name,
                    "path": str(session_dir),
                    "has_manifest": manifest_path.exists(),
                }

                if manifest_path.exists():
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        session_info["goal"] = manifest.get("goal", "")[:100]
                        session_info["generated_at"] = manifest.get("generated_at", "")
                        session_info["final_artifacts"] = manifest.get("final_artifacts", [])
                        summary = manifest.get("summary", {})
                        session_info["total_time_s"] = summary.get("total_time_s", 0)
                    except Exception:
                        pass

                sessions.append(session_info)

    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}/manifest")
async def get_session_manifest(session_id: str):
    """Get the manifest.json for a session."""
    manifest_path = OUTPUT_DIR / session_id / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="Session manifest not found")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return manifest
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/artifacts/{filename}")
async def get_session_artifact(session_id: str, filename: str):
    """Serve a generated artifact file."""
    # First try max_output, then final
    file_path = OUTPUT_DIR / session_id / "max_output" / filename
    if not file_path.exists():
        file_path = OUTPUT_DIR / session_id / "final" / filename
        
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Determine content type
    suffix = file_path.suffix.lower()
    content_types = {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".json": "application/json",
        ".py": "text/plain",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }
    content_type = content_types.get(suffix, "text/plain")

    return FileResponse(file_path, media_type=content_type)


# ── Helpers ──

def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def _find_latest_session_dir() -> Optional[Path]:
    """Find the most recently created session directory."""
    if not OUTPUT_DIR.exists():
        return None
    session_dirs = [
        d for d in OUTPUT_DIR.iterdir()
        if d.is_dir() and d.name.startswith("session_")
    ]
    if not session_dirs:
        return None
    return max(session_dirs, key=lambda d: d.stat().st_mtime)


# ── Main ──

if __name__ == "__main__":
    import uvicorn
    print("\n  🚀 Starting NexusSentry API Server...")
    print("  📡 API:      http://localhost:8000")
    print("  🌐 Frontend: http://localhost:8000")
    print("  📋 Docs:     http://localhost:8000/docs\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
