"""Write the API's OpenAPI schema as JSON, for the frontend's generated types.

    python -m scripts.export_openapi schema.json

Needs no server and no database: FastAPI builds the schema from the route signatures.
The frontend's ``npm run gen:api`` reads the file this writes (``make gen-api`` runs both).
It writes a file rather than stdout because importing the app logs to stdout.
"""

import json
import sys
from pathlib import Path

from web.api import app

EXPECTED_ARGS = 2  # the script name and the output path


def main() -> None:
    """Write the schema to the path given as the only argument, keys sorted so it diffs cleanly."""
    if len(sys.argv) != EXPECTED_ARGS:
        sys.exit("usage: python -m scripts.export_openapi OUTPUT.json")
    Path(sys.argv[1]).write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
