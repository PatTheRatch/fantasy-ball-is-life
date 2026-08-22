"""Identity-crosswalk repositories (global scope): players, provider identities,
links, and the review queue."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models.crosswalk import IdentityLink, IdentityReviewQueue, ProviderIdentity
from backend.models.nba import Player


class PlayerRepository:
    """The canonical player pool (populated by the NBA ingest; S1-09 only reads)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, player: Player) -> None:
        self.session.add(player)

    def list_active(self) -> list[Player]:
        """Every active player — the resolution candidate pool."""
        return list(
            self.session.scalars(select(Player).where(Player.is_active.is_(True)))
        )


class ProviderIdentityRepository:
    """Provider records FCP has seen, before any mapping judgement."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find(
        self,
        provider_id: uuid.UUID,
        entity_kind: str,
        provider_entity_id: str | None,
        raw_name: str | None = None,
    ) -> ProviderIdentity | None:
        """The provider record for ``(provider_id, entity_kind, key)``.

        The key is ``provider_entity_id`` when the source has a stable id, and
        ``raw_name`` (already normalised by the caller) when it does not. The two
        are deliberately *not* interchangeable: a name-only record must never
        collapse onto an id-carrying one, nor onto a different name's record —
        that conflation is exactly the "confidently wrong" auto-link D18 forbids.
        """
        stmt = select(ProviderIdentity).where(
            ProviderIdentity.provider_id == provider_id,
            ProviderIdentity.entity_kind == entity_kind,
        )
        if provider_entity_id is not None:
            stmt = stmt.where(ProviderIdentity.provider_entity_id == provider_entity_id)
        else:
            stmt = stmt.where(
                ProviderIdentity.provider_entity_id.is_(None),
                ProviderIdentity.raw_name == raw_name,
            )
        return self.session.scalars(stmt).one_or_none()

    def add(self, identity: ProviderIdentity) -> None:
        self.session.add(identity)


class IdentityLinkRepository:
    """The durable crosswalk (D19). A wrong link is superseded, never deleted."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, link: IdentityLink) -> None:
        self.session.add(link)

    def find_active(self, provider_identity_id: uuid.UUID) -> IdentityLink | None:
        """The non-superseded link for a provider identity, if any."""
        return self.session.scalars(
            select(IdentityLink).where(
                IdentityLink.provider_identity_id == provider_identity_id,
                IdentityLink.superseded_at.is_(None),
            )
        ).one_or_none()


class IdentityReviewQueueRepository:
    """Unresolved identities awaiting review (D18 — never silently dropped)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: IdentityReviewQueue) -> None:
        self.session.add(item)

    def find_open(self, provider_identity_id: uuid.UUID) -> IdentityReviewQueue | None:
        """An existing open review item for a provider identity (idempotency)."""
        return self.session.scalars(
            select(IdentityReviewQueue).where(
                IdentityReviewQueue.provider_identity_id == provider_identity_id,
                IdentityReviewQueue.status == "open",
            )
        ).one_or_none()

    def count_open(self) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(IdentityReviewQueue)
                .where(IdentityReviewQueue.status == "open")
            )
            or 0
        )
