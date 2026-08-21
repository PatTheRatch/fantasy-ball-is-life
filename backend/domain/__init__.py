"""Pure basketball logic.

**This package imports nothing from any other layer** — no api, services,
repos, providers, database, HTTP or configuration. Enforced by
``tests/test_architecture.py``.

That constraint is what makes one shared intelligence layer real rather than
aspirational (charter Decision 4): a tool cannot accidentally reinvent
category direction or player matching if the only way to get numbers is to
call a function that demands its inputs explicitly.

It is also what makes the highest-value code in the product fast to test —
no database, no fixtures, no network.
"""
