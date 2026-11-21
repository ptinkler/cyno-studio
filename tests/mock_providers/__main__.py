"""Run the mock providers: ``python -m tests.mock_providers [--port 5056]``.

Point the app at it with ``VENICE_BASE_URL=http://127.0.0.1:<port>/venice/api/v1``.
"""

import argparse

import uvicorn

from tests.mock_providers.app import app


class _Args(argparse.Namespace):
    """The parsed command line."""

    port: int = 5056


def main() -> None:
    """Serve the mock on localhost."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5056)
    args = parser.parse_args(namespace=_Args())
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
