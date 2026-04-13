# nexussentry/observability/ws_dashboard.py
"""
WebSocket Dashboard v3.0 — Real-Time Event Streaming
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Replaces HTTP polling with WebSocket streaming.
Zero delay, no wasted requests.

Falls back to HTTP polling dashboard if websockets is not installed.
"""

import asyncio
import json
import logging
import threading
from typing import Set, Optional

logger = logging.getLogger("WSDashboard")

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.info("websockets not installed — WebSocket dashboard unavailable, using HTTP polling")


class RealtimeDashboard:
    """
    WebSocket server that streams agent events to connected clients instantly.
    Thread-safe for use alongside the synchronous swarm orchestrator.
    """

    def __init__(self, tracer):
        self.tracer = tracer
        self.clients: Set = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    async def _handler(self, websocket):
        """Handle a single WebSocket connection."""
        self.clients.add(websocket)
        try:
            # Send current state immediately on connect
            state = self.tracer.get_dashboard_state()
            await websocket.send(json.dumps({
                "type": "initial_state",
                "data": state,
            }, default=str))

            # Keep connection alive until client disconnects
            async for message in websocket:
                # Client can send "ping" to keep alive
                if message == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
        except Exception:
            pass
        finally:
            self.clients.discard(websocket)

    async def broadcast_event(self, event: dict):
        """Push an event to all connected WebSocket clients."""
        if not self.clients:
            return

        message = json.dumps({
            "type": "event",
            "data": event,
        }, default=str)

        disconnected = set()
        for client in self.clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.add(client)

        self.clients -= disconnected

    def broadcast_sync(self, event: dict):
        """Thread-safe broadcast from synchronous code."""
        if not self._loop or not self.clients:
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.broadcast_event(event),
                self._loop,
            )
        except Exception:
            pass

    async def _serve(self, host: str = "localhost", port: int = 7778):
        """Start the WebSocket server."""
        async with websockets.serve(self._handler, host, port):
            logger.info(f"WebSocket dashboard running at ws://{host}:{port}")
            await asyncio.Future()  # Run forever

    def start(self, port: int = 7778):
        """Start the WebSocket server in a background thread."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("Cannot start WebSocket dashboard: websockets not installed")
            return

        def _run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._serve(port=port))
            except Exception as e:
                logger.warning(f"WebSocket dashboard failed: {e}")

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        print(f"  🔌 WebSocket Dashboard: ws://localhost:{port}")

    @property
    def connected_clients(self) -> int:
        """Number of currently connected clients."""
        return len(self.clients)
