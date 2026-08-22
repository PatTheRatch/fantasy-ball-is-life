"""Export the FastAPI OpenAPI schema to ``frontend/openapi.json``.

The frontend's generated API client is built from this *committed* snapshot, so
the backend contract and the client cannot drift silently — CI regenerates this
file and ``git diff --exit-code`` fails if the backend changed without the
snapshot being refreshed.

Run from the repo root::

    python scripts/export-openapi.py

``create_app()`` builds without a database or keyset (the route-policy matrix
test relies on the same property), so this needs no environment.
"""

from __future__ import annotations

import json
import pathlib

from backend.api.app import create_app

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "frontend" / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
