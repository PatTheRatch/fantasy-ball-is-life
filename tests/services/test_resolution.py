"""Identity resolution ladder: the one ladder, tested hermetically.

No database — ``resolve_identity`` is pure, driven with ``PlayerCandidate``
values, so every rung of the ladder (provider_id → nba_anchor → exact_name_dob →
exact_name → fuzzy → queue) is exercised without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date

from backend.domain.names import MatchMethod
from backend.services.resolution import PlayerCandidate, resolve_identity

#: Pool used by most tests: two players, distinct names + birthdates.
JOKIC = PlayerCandidate(uuid.uuid4(), "nikola jokic", date(1995, 2, 19))
TATUM = PlayerCandidate(uuid.uuid4(), "jayson tatum", date(1998, 3, 3))
POOL = [JOKIC, TATUM]


def _resolve(raw_name, birthdate=None, *, existing=None, anchor=None, pool=POOL):
    return resolve_identity(
        raw_name,
        birthdate,
        existing_link_entity_id=existing,
        nba_anchor_entity_id=anchor,
        pool=pool,
    )


# --- provider_id (existing link) -------------------------------------------


def test_existing_link_wins_over_any_name_match() -> None:
    decision = _resolve("Jayson Tatum", existing=JOKIC.fcp_entity_id)
    assert decision.action == "auto_link"
    assert decision.match_method is MatchMethod.PROVIDER_ID
    assert decision.confidence == 1.000
    assert decision.fcp_entity_id == JOKIC.fcp_entity_id


# --- nba_anchor -------------------------------------------------------------


def test_nba_anchor_auto_links() -> None:
    decision = _resolve("Some Name", anchor=TATUM.fcp_entity_id)
    assert decision.action == "auto_link"
    assert decision.match_method is MatchMethod.NBA_ANCHOR
    assert decision.confidence == 0.990
    assert decision.fcp_entity_id == TATUM.fcp_entity_id


# --- exact_name_dob ---------------------------------------------------------


def test_exact_name_and_birthdate_auto_links() -> None:
    decision = _resolve("Nikola Jokić", birthdate=date(1995, 2, 19))
    assert decision.action == "auto_link"
    assert decision.match_method is MatchMethod.EXACT_NAME_DOB
    assert decision.confidence == 0.950
    assert decision.fcp_entity_id == JOKIC.fcp_entity_id


# --- exact_name (unique) ----------------------------------------------------


def test_exact_unique_name_auto_links() -> None:
    decision = _resolve("Jayson Tatum")
    assert decision.action == "auto_link"
    assert decision.match_method is MatchMethod.EXACT_NAME
    assert decision.confidence == 0.850
    assert decision.fcp_entity_id == TATUM.fcp_entity_id


def test_exact_name_normalises_accents_and_punctuation() -> None:
    # "Jayson Tatum." → "jayson tatum" == the pool's normalised form.
    decision = _resolve("Jayson Tatum.")
    assert decision.action == "auto_link"
    assert decision.fcp_entity_id == TATUM.fcp_entity_id


# --- exact_name (ambiguous — two players share a name) ----------------------


def test_duplicate_name_queues_as_ambiguous_with_entity_ids() -> None:
    a = PlayerCandidate(uuid.uuid4(), "jalen williams", date(2001, 4, 14))
    b = PlayerCandidate(uuid.uuid4(), "jalen williams", date(2002, 1, 1))
    decision = _resolve("Jalen Williams", pool=[a, b])
    assert decision.action == "queue"
    assert decision.reason == "ambiguous"
    assert len(decision.candidates) == 2
    # The two candidates are distinguishable by entity id, so a reviewer can
    # act without re-deriving the match.
    ids = {c.fcp_entity_id for c in decision.candidates}
    assert ids == {a.fcp_entity_id, b.fcp_entity_id}


# --- fuzzy → always queued --------------------------------------------------


def test_unambiguous_fuzzy_queues_not_auto_links() -> None:
    # "Jason Tatum" is a near-miss for "Jayson Tatum" — fuzzy, so queued (policy
    # step 5: fuzzy is never auto-linked).
    decision = _resolve("Jason Tatum")
    assert decision.action == "queue"
    assert decision.reason == "fuzzy_name"
    assert decision.candidates


def test_low_confidence_queues() -> None:
    decision = _resolve("Completely Different Name")
    assert decision.action == "queue"
    assert decision.reason == "low_confidence"


def test_empty_pool_queues() -> None:
    decision = _resolve("Jalen Williams", pool=[])
    assert decision.action == "queue"
    assert decision.reason == "empty_pool"


def test_empty_name_queues() -> None:
    decision = _resolve(None)
    assert decision.action == "queue"
    assert decision.reason == "empty_name"
