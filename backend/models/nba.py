"""NBA foundation models.

Only the minimal slice of ``03-nba`` that ``02-fantasy`` references now:
``NbaSeason`` (the FK target of ``league_seasons.nba_season_id``). The rest of
the NBA domain — ``nba_teams``, ``players``, ``nba_games`` — lands with the
player-identity (S1-09) and NBA-foundation bites.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import CreatedAtMixin, uuid7
from backend.platform.db import Base


class NbaSeason(CreatedAtMixin, Base):
    """A canonical NBA season. Scope: ``global`` · Freshness: ``reference``.

    ``season_year`` is the *ending* calendar year (2026 == 2025-26), matching
    ESPN's convention — documented here so no domain re-derives it (03-nba).
    """

    __tablename__ = "nba_seasons"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    season_year: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    all_star_break_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    all_star_break_end: Mapped[date | None] = mapped_column(Date, nullable=True)
