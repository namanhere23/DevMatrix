# nexussentry/observability/dashboard.py
"""
Dashboard Server — Real-Time Agent Observability
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Serves a stunning glassmorphism dashboard that shows
agents working in real-time via 1-second polling.

Uses Python's built-in http.server — zero dependencies.
"""

import json
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

logger = logging.getLogger("Dashboard")

# Global reference to the tracer — set by start_dashboard()
_tracer = None


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/state":
            self._serve_state()
        elif self.path == "/api/events":
            self._serve_events()
        elif self.path == "/api/providers":
            self._serve_providers()
        else:
            self.send_error(404)

    def _serve_html(self):
        """Serve the dashboard HTML file."""
        html_path = Path(__file__).parent / "static" / "index.html"
        if html_path.exists():
            content = html_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(500, "Dashboard HTML not found")

    def _serve_state(self):
        """Return current dashboard state as JSON."""
        global _tracer
        if _tracer:
            state = _tracer.get_dashboard_state()
        else:
            state = {"status": "waiting", "events": []}

        body = json.dumps(state, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self):
        """Return events since last poll."""
        global _tracer
        # Parse ?since=N from query string
        since = 0
        if "?" in self.path:
            params = dict(p.split("=") for p in self.path.split("?")[1].split("&") if "=" in p)
            try:
                since = int(params.get("since", 0))
            except ValueError:
                since = 0

        if _tracer:
            events = _tracer.get_events_since(since)
        else:
            events = []

        body = json.dumps({"events": events, "total": len(_tracer.events) if _tracer else 0},
                          default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_providers(self):
        """Return provider statistics."""
        try:
            from nexussentry.providers.llm_provider import get_provider
            stats = get_provider().stats()
        except ImportError:
            stats = {}

        body = json.dumps(stats, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Suppress default request logging to keep console clean."""
        pass


def start_dashboard(tracer, port: int = 7777) -> threading.Thread:
    """
    Start the dashboard server in a background thread.
    Returns the thread handle.
    """
    global _tracer
    _tracer = tracer

    server = HTTPServer(("127.0.0.1", port), DashboardHandler)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    logger.info(f"Dashboard running at http://localhost:{port}")
    print(f"\n  🌐 Dashboard: http://localhost:{port}")

    return thread
