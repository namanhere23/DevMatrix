"""Run the NexusSentry FastAPI backend with ``python -m nexussentry.api``."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("NEXUSSENTRY_API_HOST", "127.0.0.1")
    port = int(os.getenv("NEXUSSENTRY_API_PORT", "8000"))
    uvicorn.run("nexussentry.api.app:create_app", factory=True, host=host, port=port)


if __name__ == "__main__":
    main()
