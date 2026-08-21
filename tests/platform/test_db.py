"""SQLAlchemy base, engine and session factory: no import-time side effects."""

from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.platform.db import NAMING_CONVENTION, Base, make_engine, make_session_factory


def test_base_carries_the_naming_convention() -> None:
    """Stable constraint names so migrations are reviewable (schema README)."""
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert NAMING_CONVENTION["uq"] == "uq_%(table_name)s_%(column_0_name)s"
    assert NAMING_CONVENTION["pk"] == "pk_%(table_name)s"


def test_make_engine_returns_an_engine() -> None:
    engine = make_engine("sqlite:///:memory:")
    try:
        assert isinstance(engine, Engine)
    finally:
        engine.dispose()


def test_make_session_factory_returns_a_factory() -> None:
    engine = make_engine("sqlite:///:memory:")
    try:
        factory = make_session_factory(engine)
        assert isinstance(factory, sessionmaker)
        assert isinstance(factory(), Session)
    finally:
        engine.dispose()
