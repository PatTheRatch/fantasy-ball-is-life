"""H-05a: the database rejects the bad rows (Postgres).

Each of the four additive constraints needs a test that *Postgres* rejects the
bad row — not that the application avoids writing it. SQLite does not enforce
partial unique indexes the same way, so these run only when
``TEST_DATABASE_URL`` is set (CI provides Postgres and sets it).
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.models.crosswalk import (
    IdentityLink,
    IdentityReviewQueue,
    ProviderIdentity,
)
from backend.models.fantasy import League, LeagueSeason, MatchupPeriod
from backend.models.ingestion import IngestionRun
from backend.models.nba import NbaSeason
from backend.repos.crosswalk import (
    IdentityLinkRepository,
    IdentityReviewQueueRepository,
    PlayerRepository,
    ProviderIdentityRepository,
)
from backend.repos.ingestion import ProviderRepository
from backend.services.resolution import IdentityResolutionService


def _clean(db_session: Session) -> None:
    for table in (
        "identity_review_queue",
        "identity_links",
        "provider_identities",
        "matchup_periods",
        "league_seasons",
        "leagues",
        "nba_seasons",
        "ingestion_runs",
    ):
        db_session.execute(text(f'TRUNCATE "{table}" CASCADE'))
    db_session.commit()


def _espn_id(db_session: Session) -> uuid.UUID:
    provider = ProviderRepository(db_session).get_by_key("espn")
    assert provider is not None, "espn provider should be seeded"
    return provider.id


def _identity(
    db_session: Session, provider_id: uuid.UUID, *, name: str | None, key: str
) -> ProviderIdentity:
    """A provider identity with a distinct ``provider_entity_id`` so repeated
    calls never collide with each other."""
    identity = ProviderIdentity(
        provider_id=provider_id, entity_kind="player",
        provider_entity_id=key, raw_name=name,
    )
    db_session.add(identity)
    db_session.flush()
    return identity


def _run(db_session: Session, provider_id: uuid.UUID) -> IngestionRun:
    run = IngestionRun(provider_id=provider_id, kind="matchups", normalizer_version="test")
    db_session.add(run)
    db_session.flush()
    return run


def _season_id(db_session: Session) -> uuid.UUID:
    year = 3000 + uuid.uuid4().int % 500
    nba = NbaSeason(
        season_year=year, label=f"test {year}",
        start_date=date(2020, 1, 1), end_date=date(2020, 6, 1),
    )
    league = League(slug=f"test-{uuid.uuid4().hex[:8]}", name="Test League")
    db_session.add_all([nba, league])
    db_session.flush()
    season = LeagueSeason(
        league_id=league.id, nba_season_id=nba.id, season_year=year,
        provider_key="espn", provider_league_id="1", scoring_type="h2h_categories",
    )
    db_session.add(season)
    # Commit (not just flush): the period inserts that follow fail with
    # IntegrityError and roll back, and the season must survive those rollbacks.
    db_session.commit()
    return season.id


# --- 1 · name-only provider identities are unique ----------------------------


def test_name_only_identities_unique(db_session: Session) -> None:
    _clean(db_session)
    provider_id = _espn_id(db_session)

    def _name_only(name: str) -> ProviderIdentity:
        return ProviderIdentity(
            provider_id=provider_id, entity_kind="player",
            provider_entity_id=None, raw_name=name,
        )

    db_session.add(_name_only("lebron james"))
    db_session.commit()

    # A second name-only identity with the same (provider, kind, name) → rejected.
    with pytest.raises(IntegrityError):
        db_session.add(_name_only("lebron james"))
        db_session.commit()
    db_session.rollback()

    # A third carrying a provider_entity_id with the same name → accepted (the
    # index is partial; it must not reject legitimate id-bearing duplicates).
    db_session.add(
        ProviderIdentity(
            provider_id=provider_id, entity_kind="player",
            provider_entity_id="espn-123", raw_name="lebron james",
        )
    )
    db_session.commit()


# --- 2 · one open review item per identity -----------------------------------


def test_one_open_review_per_identity(db_session: Session) -> None:
    _clean(db_session)
    provider_id = _espn_id(db_session)
    identity = _identity(db_session, provider_id, name="someone", key="q-identity")
    run = _run(db_session, provider_id)
    db_session.add(
        IdentityReviewQueue(
            provider_identity_id=identity.id, ingestion_run_id=run.id,
            reason="no_candidate", status="open",
        )
    )
    db_session.commit()

    # A second open row for the same identity → rejected.
    with pytest.raises(IntegrityError):
        db_session.add(
            IdentityReviewQueue(
                provider_identity_id=identity.id, ingestion_run_id=run.id,
                reason="no_candidate", status="open",
            )
        )
        db_session.commit()
    db_session.rollback()

    # A resolved row for the same identity → accepted.
    db_session.add(
        IdentityReviewQueue(
            provider_identity_id=identity.id, ingestion_run_id=run.id,
            reason="no_candidate", status="resolved",
        )
    )
    db_session.commit()


# --- 3 · confidence is a probability -----------------------------------------


def _link(db_session: Session, provider_id: uuid.UUID, confidence: float) -> None:
    identity = _identity(
        db_session, provider_id, name=None, key=f"conf-{uuid.uuid4().hex[:8]}"
    )
    db_session.add(
        IdentityLink(
            provider_identity_id=identity.id, fcp_entity_kind="player",
            fcp_entity_id=uuid.uuid4(), match_method="manual", confidence=confidence,
        )
    )


def test_confidence_is_bounded(db_session: Session) -> None:
    _clean(db_session)
    provider_id = _espn_id(db_session)

    for bad in (1.5, -0.1):
        with pytest.raises(IntegrityError):
            _link(db_session, provider_id, bad)
            db_session.commit()
        db_session.rollback()

    # Boundaries inclusive.
    _link(db_session, provider_id, 0.0)
    _link(db_session, provider_id, 1.0)
    db_session.commit()


# --- 4 · finality and its timestamp agree ------------------------------------


def test_finality_requires_timestamp(db_session: Session) -> None:
    _clean(db_session)
    season_id = _season_id(db_session)

    def _period(ordinal: int, status: str, finalized_at: datetime | None) -> MatchupPeriod:
        return MatchupPeriod(
            league_season_id=season_id, ordinal=ordinal, status=status,
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 7),
            finalized_at=finalized_at,
        )

    # final without a finalized_at → rejected.
    with pytest.raises(IntegrityError):
        db_session.add(_period(1, "final", None))
        db_session.commit()
    db_session.rollback()

    # scheduled *with* a finalized_at → also rejected (equivalence, not implication).
    with pytest.raises(IntegrityError):
        db_session.add(_period(2, "scheduled", datetime(2026, 1, 7, 12, 0, 0)))
        db_session.commit()
    db_session.rollback()

    # A consistent final period → accepted.
    db_session.add(_period(3, "final", datetime(2026, 1, 7, 12, 0, 0)))
    db_session.commit()


# --- 5 · concurrent resolution converges on one row --------------------------


def _service(session: Session) -> IdentityResolutionService:
    return IdentityResolutionService(
        ProviderIdentityRepository(session),
        IdentityLinkRepository(session),
        IdentityReviewQueueRepository(session),
        PlayerRepository(session),
    )


def test_concurrent_resolution_converges(
    migrated_session_factory: sessionmaker[Session],
) -> None:
    with migrated_session_factory() as seed:
        _clean(seed)
        provider_id = _espn_id(seed)

    factory = migrated_session_factory
    barrier = threading.Barrier(2)
    ids: list[uuid.UUID] = []
    errors: list[BaseException] = []

    def resolve() -> None:
        session = factory()
        try:
            service = _service(session)
            barrier.wait()
            identity = service._get_or_create_identity(  # noqa: SLF001 — under test
                provider_id, "player", None, "lebron james"
            )
            session.commit()
            ids.append(identity.id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    threads = [threading.Thread(target=resolve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == [], f"concurrent resolution must not raise: {errors}"
    assert len(ids) == 2
    assert ids[0] == ids[1], "both transactions must converge on the same identity"

    with migrated_session_factory() as check:
        count = check.scalar(
            select(func.count())
            .select_from(ProviderIdentity)
            .where(
                ProviderIdentity.provider_entity_id.is_(None),
                ProviderIdentity.raw_name == "lebron james",
            )
        )
        assert count == 1, "exactly one name-only identity must exist"
