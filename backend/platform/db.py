"""SQLAlchemy 2.0 engine, session factory, and declarative base.

``Base`` carries a ``MetaData`` naming convention so that Alembic autogenerate
and any hand-written migration produce stable, reviewable constraint names
(``uq_<table>_<col>`` rather than the database's auto-generated gibberish).

Nothing is constructed at import time. Call :func:`make_engine` and
:func:`make_session_factory` when a real database connection is needed.
"""

from __future__ import annotations

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

#: Stable constraint/index names, per docs/v2/schema/README.md §Migrations
#: ("one concern per migration", reviewable diffs).
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    No models exist yet — S1-05 adds the first tables on top of this base.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def make_engine(url: str) -> Engine:
    """Build a synchronous SQLAlchemy engine for ``url``.

    Sync, not async, is a deliberate choice for the persistence foundation:
    correctness before performance (D20), and no web layer exists yet that
    would benefit from an async driver. Revisit at the read path (S1-10).
    """
    return create_engine(url)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``."""
    return sessionmaker(bind=engine)
