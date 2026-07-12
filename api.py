"""Deprecated entrypoint shim.

The FastAPI app moved to `backend/api/main.py` as part of the backend
package restructure (docs/specs/BACKEND_RESTRUCTURE.md). Use
`uvicorn backend.api.main:app` going forward.

This file exists for one release so `uvicorn api:app` (shell history,
external server config) doesn't break outright -- delete it once nothing
references this path (spec Section 6).
"""
from backend.api.main import app  # noqa: F401
