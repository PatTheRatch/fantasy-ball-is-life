"""Typed projection-availability errors.

The draft optimizer needs a season-horizon projection source. There are two
ways to supply one:

  1. Activate a season ``ProjectionSet`` in the store (the P-2/P-6 upload
     flow — BBM/Hashtag/custom, and eventually FCP).
  2. Drop the legacy on-disk workbook at ``BBM_PROJECTIONS_PATH``.

When neither exists, the optimizer used to hit a bare ``pd.read_excel`` and
raise ``FileNotFoundError``, which the routers' generic ``except Exception``
turned into a 500 with the server's absolute filesystem path in the body.
That is both a poor UX (the user can't tell what to do) and needless
infrastructure disclosure.

``MissingProjectionsError`` subclasses ``ValueError`` deliberately: the draft
routers already map ``ValueError`` → 422, so the clean status survives even
on routes that predate the app-wide handler in ``backend.api.main``.
"""

from __future__ import annotations


class MissingProjectionsError(ValueError):
    """No season-horizon projections are available from any source."""


def missing_projections_message() -> str:
    """User-facing remedy text. Deliberately names no filesystem path."""
    return (
        "No season projections are active. Upload a projection set "
        "(Settings → Projections) or activate an existing one before "
        "generating draft plans."
    )
