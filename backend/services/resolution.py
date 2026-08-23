"""Identity resolution: the one ladder that ties provider records to FCP players.

Charter D18 ("prefer unknown over confidently wrong") and D19 (the permanent
crosswalk). The ladder is the 04-provider-ingestion "Resolution policy", defined
*once* here and used by every ingest — no per-call-site thresholds. It delegates
name comparison to ``domain.names`` (``normalize_name`` + ``match_name``), so
there is a single name-normalisation implementation.

The pure :func:`resolve_identity` is the ladder; :class:`IdentityResolutionService`
wraps it with the get-or-create + write steps. An unmatched name is queued and
counted, never dropped (the V1 behaviour this exists to end).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError

from backend.domain.names import CONFIDENCE, MatchMethod, match_name, normalize_name
from backend.models.crosswalk import (
    IdentityLink,
    IdentityReviewQueue,
    ProviderIdentity,
)
from backend.repos.crosswalk import (
    IdentityLinkRepository,
    IdentityReviewQueueRepository,
    PlayerRepository,
    ProviderIdentityRepository,
)

#: Auto-link methods, strongest first (04 §Resolution policy).
_AUTO_LINK_METHODS = (
    MatchMethod.PROVIDER_ID,
    MatchMethod.NBA_ANCHOR,
    MatchMethod.EXACT_NAME_DOB,
    MatchMethod.EXACT_NAME,
)


@dataclass(frozen=True, slots=True)
class PlayerCandidate:
    """One FCP player as a resolution target."""

    fcp_entity_id: uuid.UUID
    normalized_name: str
    birthdate: date | None


@dataclass(frozen=True, slots=True)
class QueueCandidate:
    """One near-miss, with its entity id so a reviewer can act without re-deriving."""

    fcp_entity_id: uuid.UUID | None
    name: str
    score: float


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    """The ladder's verdict: auto-link to an entity, or queue for review."""

    action: str  # "auto_link" | "queue"
    match_method: MatchMethod | None
    confidence: float | None
    fcp_entity_id: uuid.UUID | None
    # queue reason: empty_name|empty_pool|no_candidate|ambiguous|dob_conflict|
    # low_confidence|fuzzy_name
    reason: str | None
    candidates: tuple[QueueCandidate, ...]


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """What the service did with one provider record."""

    identity: ProviderIdentity
    decision: ResolutionDecision
    link: IdentityLink | None = None
    queued: IdentityReviewQueue | None = None


def _auto_link(method: MatchMethod, fcp_entity_id: uuid.UUID) -> ResolutionDecision:
    """Build an auto-link decision, looking up the method's confidence."""
    return ResolutionDecision(
        "auto_link", method, CONFIDENCE[method], fcp_entity_id, None, ()
    )


def _queue(reason: str, candidates: tuple[QueueCandidate, ...] = ()) -> ResolutionDecision:
    """Build a queue decision with its reason and near-miss evidence."""
    return ResolutionDecision("queue", None, None, None, reason, candidates)


def _two_sided_dob_conflict(birthdate: date | None, candidate: PlayerCandidate) -> bool:
    """True iff both sides carry a birthdate and they disagree.

    charter D18: prefer unknown over confidently wrong. Only a *two-sided*
    disagreement is a conflict — a candidate with ``birthdate=None`` is missing
    evidence, not contradicting evidence, and must stay eligible to auto-link.
    """
    return (
        birthdate is not None
        and candidate.birthdate is not None
        and candidate.birthdate != birthdate
    )


def resolve_identity(
    raw_name: str | None,
    birthdate: date | None,
    *,
    existing_link_entity_id: uuid.UUID | None,
    nba_anchor_entity_id: uuid.UUID | None,
    pool: Iterable[PlayerCandidate],
) -> ResolutionDecision:
    """The resolution ladder (04 §Resolution policy), one implementation.

    1. ``provider_id`` — an existing link wins (1.000).
    2. ``nba_anchor`` — a provider-exposed NBA id already crosswalked (0.990).
    3. ``exact_name_dob`` — normalised name *and* birthdate (0.950).
    4. ``exact_name`` — normalised name, unique in the pool and not refuted by
       a two-sided birthdate disagreement (0.850).
    5. ``fuzzy_name`` — above threshold, unambiguous → **queue** (never auto-link).
    6. anything else → **queue**.
    """
    candidates = list(pool)

    if existing_link_entity_id is not None:
        return _auto_link(MatchMethod.PROVIDER_ID, existing_link_entity_id)

    if nba_anchor_entity_id is not None:
        return _auto_link(MatchMethod.NBA_ANCHOR, nba_anchor_entity_id)

    needle = normalize_name(raw_name)
    if not needle:
        return _queue("empty_name")

    # exact_name_dob — the strongest name-only disambiguator.
    if birthdate is not None:
        dob_matches = [
            c for c in candidates if c.normalized_name == needle and c.birthdate == birthdate
        ]
        if dob_matches:
            return _auto_link(MatchMethod.EXACT_NAME_DOB, dob_matches[0].fcp_entity_id)

    # exact_name — unique and not refuted. Partition first: a two-sided
    # birthdate disagreement is a conflict, not a fall-through, so a reviewer
    # sees *why* the name matched but the link must not be made (charter D18).
    # A candidate with no birthdate is missing evidence and stays eligible.
    exact = [c for c in candidates if c.normalized_name == needle]
    exact_conflict = [c for c in exact if _two_sided_dob_conflict(birthdate, c)]
    exact_ok = [c for c in exact if not _two_sided_dob_conflict(birthdate, c)]

    if len(exact_ok) == 1:
        return _auto_link(MatchMethod.EXACT_NAME, exact_ok[0].fcp_entity_id)
    if len(exact_ok) > 1:
        evidence = tuple(
            QueueCandidate(c.fcp_entity_id, c.normalized_name, 100.0) for c in exact_ok
        )
        return _queue("ambiguous", evidence)
    if exact_conflict:
        evidence = tuple(
            QueueCandidate(c.fcp_entity_id, c.normalized_name, 100.0)
            for c in exact_conflict
        )
        return _queue("dob_conflict", evidence)

    # fuzzy — always queued, even when unambiguous (policy step 5). Map the
    # fuzzy-matched pool names back to their entity ids for actionable evidence.
    outcome = match_name(needle, [c.normalized_name for c in candidates])
    by_name = {c.normalized_name: c for c in candidates}
    evidence = tuple(
        QueueCandidate(
            by_name[m.key].fcp_entity_id if m.key in by_name else None,
            m.key,
            m.score,
        )
        for m in outcome.candidates
    )
    if outcome.matched is None:
        return _queue(outcome.reason or "no_candidate", evidence)
    return _queue("fuzzy_name", evidence)


class IdentityResolutionService:
    """Resolves provider records to FCP players, linking or queueing."""

    def __init__(
        self,
        identities: ProviderIdentityRepository,
        links: IdentityLinkRepository,
        review: IdentityReviewQueueRepository,
        players: PlayerRepository,
    ) -> None:
        self.identities = identities
        self.links = links
        self.review = review
        self.players = players

    def resolve_and_link(
        self,
        *,
        provider_id: uuid.UUID,
        provider_entity_id: str | None,
        raw_name: str | None,
        birthdate: date | None,
        ingestion_run_id: uuid.UUID,
        nba_anchor_entity_id: uuid.UUID | None = None,
        entity_kind: str = "player",
    ) -> ResolutionResult:
        """Resolve one provider record and record the outcome.

        Idempotent: an active link for this identity is returned unchanged, and
        an existing open review item is returned rather than re-added — so
        re-running an ingest neither re-matches nor inflates the open queue.
        """
        needle = normalize_name(raw_name)
        identity = self._get_or_create_identity(
            provider_id, entity_kind, provider_entity_id, needle
        )

        existing = self.links.find_active(identity.id)
        if existing is not None:
            decision = ResolutionDecision(
                "auto_link", MatchMethod.PROVIDER_ID, 1.000, existing.fcp_entity_id, None, ()
            )
            return ResolutionResult(identity, decision, link=existing)

        pool = (
            PlayerCandidate(c.id, normalize_name(c.full_name), c.birthdate)
            for c in self.players.list_active()
        )
        decision = resolve_identity(
            raw_name,
            birthdate,
            existing_link_entity_id=None,
            nba_anchor_entity_id=nba_anchor_entity_id,
            pool=pool,
        )

        if decision.action == "auto_link":
            method = decision.match_method or MatchMethod.MANUAL
            link = IdentityLink(
                provider_identity_id=identity.id,
                fcp_entity_kind=entity_kind,
                fcp_entity_id=decision.fcp_entity_id,
                match_method=method.value,
                confidence=decision.confidence or 0.0,
            )
            self.links.add(link)
            return ResolutionResult(identity, decision, link=link)

        # Queue path — idempotent: return an existing open item for this identity
        # rather than re-adding, so re-ingesting doesn't inflate the open queue.
        queued = self._enqueue(identity, ingestion_run_id, decision)
        return ResolutionResult(identity, decision, queued=queued)

    def _get_or_create_identity(
        self,
        provider_id: uuid.UUID,
        entity_kind: str,
        provider_entity_id: str | None,
        needle: str | None,
    ) -> ProviderIdentity:
        """Get-or-create the provider identity, converging under the name-only
        unique index when two resolutions race.

        The check-then-insert was idempotent only without concurrency; the index
        makes it correct by turning a concurrent double-insert into an
        ``IntegrityError``. The insert runs in a SAVEPOINT so the losing
        transaction can roll back just that insert and re-read the winner —
        without the savepoint the whole session is poisoned and the run dies.
        """
        identity = self.identities.find(
            provider_id, entity_kind, provider_entity_id, needle
        )
        if identity is not None:
            return identity

        try:
            with self.identities.session.begin_nested():
                identity = ProviderIdentity(
                    provider_id=provider_id,
                    entity_kind=entity_kind,
                    provider_entity_id=provider_entity_id,
                    # Normalised form is the stable key for name-only sources (the
                    # truly-raw name is preserved in raw_payloads, D16).
                    raw_name=needle,
                )
                self.identities.add(identity)
                self.identities.session.flush()
                return identity
        except IntegrityError:
            # Another transaction inserted the same identity first; read the row
            # it won rather than forking a second durable identity.
            winner = self.identities.find(
                provider_id, entity_kind, provider_entity_id, needle
            )
            if winner is None:
                # Not the race this handles — some other constraint fired.
                raise
            return winner

    def _enqueue(
        self,
        identity: ProviderIdentity,
        ingestion_run_id: uuid.UUID,
        decision: ResolutionDecision,
    ) -> IdentityReviewQueue:
        """Queue an unresolved identity, converging on one open item under
        concurrency (same savepoint/retry pattern as ``_get_or_create_identity``)."""
        existing_item = self.review.find_open(identity.id)
        if existing_item is not None:
            return existing_item

        try:
            with self.identities.session.begin_nested():
                queued = IdentityReviewQueue(
                    provider_identity_id=identity.id,
                    ingestion_run_id=ingestion_run_id,
                    reason=decision.reason or "no_candidate",
                    candidates=[
                        {
                            "fcp_entity_id": str(c.fcp_entity_id) if c.fcp_entity_id else None,
                            "name": c.name,
                            "score": c.score,
                        }
                        for c in decision.candidates
                    ],
                )
                self.review.add(queued)
                self.identities.session.flush()
                return queued
        except IntegrityError:
            # Another transaction enqueued this identity first; return its item.
            winner = self.review.find_open(identity.id)
            if winner is None:
                # Not the race this handles — some other constraint fired.
                raise
            return winner
