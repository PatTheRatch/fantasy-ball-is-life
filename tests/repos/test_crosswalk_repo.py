"""Crosswalk repositories: name-only identity lookup must not conflate.

Postgres-backed (``TEST_DATABASE_URL``). This is the regression test for the
S1-09 review blocker: a name-only provider record (``provider_entity_id IS
NULL``) must key on its name, never collapse onto another name-only record.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.models.crosswalk import ProviderIdentity
from backend.repos.crosswalk import ProviderIdentityRepository
from backend.repos.ingestion import ProviderRepository


def _clean(db_session: Session) -> None:
    for table in (
        "identity_review_queue",
        "identity_links",
        "provider_identities",
        "players",
    ):
        db_session.execute(text(f'TRUNCATE "{table}" CASCADE'))
    db_session.commit()


def _espn_id(db_session: Session):
    provider = ProviderRepository(db_session).get_by_key("espn")
    assert provider is not None, "espn provider should be seeded"
    return provider.id


def test_name_only_lookup_keys_on_name_not_null_id(db_session: Session) -> None:
    _clean(db_session)
    provider_id = _espn_id(db_session)
    repo = ProviderIdentityRepository(db_session)

    lebron = ProviderIdentity(
        provider_id=provider_id, entity_kind="player", provider_entity_id=None,
        raw_name="lebron james",
    )
    curry = ProviderIdentity(
        provider_id=provider_id, entity_kind="player", provider_entity_id=None,
        raw_name="stephen curry",
    )
    db_session.add_all([lebron, curry])
    db_session.commit()

    found = repo.find(provider_id, "player", None, "lebron james")
    assert found is not None
    assert found.id == lebron.id

    found_curry = repo.find(provider_id, "player", None, "stephen curry")
    assert found_curry is not None
    assert found_curry.id == curry.id
    assert found_curry.id != found.id, "distinct name-only records must not conflate"


def test_id_carrying_lookup_does_not_match_name_only(db_session: Session) -> None:
    _clean(db_session)
    provider_id = _espn_id(db_session)
    repo = ProviderIdentityRepository(db_session)

    name_only = ProviderIdentity(
        provider_id=provider_id, entity_kind="player", provider_entity_id=None,
        raw_name="lebron james",
    )
    db_session.add(name_only)
    db_session.commit()

    # A record *with* an id must not collapse onto the name-only one.
    assert repo.find(provider_id, "player", "12345") is None
    assert repo.find(provider_id, "player", None, "lebron james") is not None
