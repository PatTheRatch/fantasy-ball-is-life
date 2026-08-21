"""Persistence foundation: settings, SQLAlchemy engine, and migrations.

This is an infrastructure layer. The domain must never import it — that rule is
enforced by ``tests/test_architecture.py`` (``backend.platform`` is a forbidden
layer). Nothing in this package acts at import time: no environment reads, no
engine construction, no filesystem access.
"""
