"""Run the app for the end-to-end tests: a fresh data folder, dev login, providers pointed at the mock.

``python -m scripts.e2e_app [--port 5057] [--mock http://127.0.0.1:5056]``. Serves the built frontend
(``src/js/dist``), so build it first. Nothing here reaches a real provider: every base URL is the mock's.
"""

import argparse
import os
import tempfile

import uvicorn


class _Args(argparse.Namespace):
    """The parsed command line."""

    port: int = 5057
    mock: str = "http://127.0.0.1:5056"


def main() -> None:
    """Set the environment, then start the app (imported after, since it reads the environment on import)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5057)
    parser.add_argument("--mock", default="http://127.0.0.1:5056")
    args = parser.parse_args(namespace=_Args())
    data = tempfile.mkdtemp(prefix="cyno-e2e-")
    os.environ.update(
        {
            "CYNO_DATA_DIR": data,
            "CYNO_DB_DIR": data,
            "CYNO_CACHE_DIR": f"{data}/cache",
            "DEV_LOGIN": "1",
            "DEV_EMAIL": "e2e@local",
            "POLLO_API_KEY": "",
            "CYNO_VIDEO_POLL_SECONDS": "0.5",
            # Tests delete and create threads back to back: the media list must never be a stale copy
            "MEDIA_LIST_TTL": "0",
            "VENICE_BASE_URL": f"{args.mock}/venice/api/v1",
            "OPENROUTER_BASE_URL": f"{args.mock}/openrouter/api/v1",
        }
    )
    uvicorn.run("web.api:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
