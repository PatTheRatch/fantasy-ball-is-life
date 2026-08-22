"""NBA foundation models.

``NbaSeason`` (the FK target of ``league_seasons.nba_season_id``) landed in
S1-06; ``Player`` (the canonical FCP player, the keystone the whole platform
pivots on) lands in S1-09 with the identity crosswalk. The rest of ``03-nba`` —
``nba_teams``, ``nba_games``, ``player_seasons`` — lands with later bites.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import CreatedAtMixin, TimestampMixin, uuid7
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


class Player(TimestampMixin, Base):
    """The canonical FCP player. Scope: ``global`` · Freshness: ``reference``.

    Deliberately carries **no** external-id columns and **no** unique constraint
    on name (03-nba): two players can share a name, and names change. External
    identifiers are crosswalk rows (D19); name-based matching is an *ingest*
    concern that lives in ``provider_identities`` → ``identity_links``, never in
    this table. ``birthdate`` is the highest-value disambiguator and is ingested
    early for that reason.
    """

    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    height_inches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_lbs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_position: Mapped[str | None] = mapped_column(Text, nullable=True)
    debut_season_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (Index("players_last_name_idx", text("lower(last_name)")),)
