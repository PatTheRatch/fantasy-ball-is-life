"""Player-name normalisation and candidate matching.

**One implementation.** V1 had two functions both called ``normalize_name`` —
one at module scope stripping accents and punctuation, one shadowed inside
``add_bbm_projections`` stripping every non-alphabetic character. They disagree
on hyphenated and suffixed names, so the same player could resolve on one code
path and vanish on another. The module-scope version is ported here and is the
only one.

**One threshold ladder.** V1 carried four fuzzy cutoffs at four call sites
(80, 75, 85, 90). Here the ladder is data, defined once, and the confidence it
produces is recorded against the match so a weak link can be audited later.

Names are *not* the join key. This module exists to support identity
resolution at ingest, which writes a durable FCP player id into the crosswalk.
Nothing downstream should ever join on a normalised name — charter
non-negotiable: "no player identity strategy based primarily on fuzzy names."
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from rapidfuzz import fuzz, process

_PUNCT = re.compile(r"[.']")
_WHITESPACE = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """Canonical comparison form for a player name.

    Strips accents, lowercases, removes periods and apostrophes, and collapses
    whitespace. Deliberately **keeps** hyphens and digits: "Gilgeous-Alexander"
    and "Jaren Jackson Jr" must not collapse into forms that collide with
    other players.
    """
    if name is None:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _PUNCT.sub("", text)
    return _WHITESPACE.sub(" ", text).strip()


class MatchMethod(StrEnum):
    """How a provider record was tied to an FCP entity, strongest first."""

    PROVIDER_ID = "provider_id"
    NBA_ANCHOR = "nba_anchor"
    EXACT_NAME_DOB = "exact_name_dob"
    EXACT_NAME = "exact_name"
    FUZZY_NAME = "fuzzy_name"
    MANUAL = "manual"


#: Confidence assigned by each method. Data, not literals at call sites.
CONFIDENCE: dict[MatchMethod, float] = {
    MatchMethod.PROVIDER_ID: 1.000,
    MatchMethod.NBA_ANCHOR: 0.990,
    MatchMethod.EXACT_NAME_DOB: 0.950,
    MatchMethod.EXACT_NAME: 0.850,
    MatchMethod.MANUAL: 1.000,
}

#: A fuzzy score below this is never auto-linked, only queued.
FUZZY_FLOOR = 70.0

#: Two candidates within this many points are ambiguous, and ambiguity always
#: queues regardless of absolute score — "prefer unknown over confidently
#: wrong" (charter Decision 18).
AMBIGUITY_MARGIN = 5.0


@dataclass(frozen=True, slots=True)
class Candidate:
    """One possible match, with the evidence for it."""

    key: str
    score: float

    @property
    def confidence(self) -> float:
        """Fuzzy score mapped into the 0.700–0.849 confidence band."""
        span = 100.0 - FUZZY_FLOOR
        pos = max(0.0, min(self.score - FUZZY_FLOOR, span))
        return round(0.700 + (pos / span) * 0.149, 3)


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    """The result of trying to resolve one name.

    ``matched`` is None when the name must be queued for review. ``reason``
    then says why, so the queue row is self-explanatory.
    """

    matched: Candidate | None
    candidates: tuple[Candidate, ...]
    reason: str | None = None


def match_name(
    raw_name: str | None,
    pool: Iterable[str],
    *,
    limit: int = 5,
) -> MatchOutcome:
    """Resolve ``raw_name`` against a pool of already-normalised names.

    Returns an outcome rather than a name-or-None, because *why* a match failed
    is the information the review queue needs. A caller must treat
    ``matched is None`` as "queue this", never as "skip this" — silently
    dropping unmatched players is the V1 behaviour this exists to end.
    """
    needle = normalize_name(raw_name)
    if not needle:
        return MatchOutcome(None, (), reason="empty_name")

    pool_list = list(pool)
    if not pool_list:
        return MatchOutcome(None, (), reason="empty_pool")

    if needle in pool_list:
        return MatchOutcome(Candidate(needle, 100.0), (Candidate(needle, 100.0),))

    raw = process.extract(needle, pool_list, scorer=fuzz.ratio, limit=limit)
    candidates = tuple(Candidate(key=name, score=float(score)) for name, score, _ in raw)
    if not candidates:
        return MatchOutcome(None, (), reason="no_candidate")

    best = candidates[0]
    if best.score < FUZZY_FLOOR:
        return MatchOutcome(None, candidates, reason="low_confidence")

    runner_up = candidates[1] if len(candidates) > 1 else None
    if runner_up is not None and (best.score - runner_up.score) < AMBIGUITY_MARGIN:
        return MatchOutcome(None, candidates, reason="ambiguous")

    return MatchOutcome(best, candidates)


def match_all(
    raw_names: Sequence[str | None],
    pool: Iterable[str],
) -> tuple[dict[str, Candidate], list[tuple[str | None, MatchOutcome]]]:
    """Resolve many names. Returns ``(resolved, unresolved)``.

    The split is the point: callers get what matched *and* an explicit list of
    what did not, so coverage is measurable and nothing disappears quietly.
    """
    pool_list = list(pool)
    resolved: dict[str, Candidate] = {}
    unresolved: list[tuple[str | None, MatchOutcome]] = []

    for raw in raw_names:
        outcome = match_name(raw, pool_list)
        if outcome.matched is not None:
            resolved[normalize_name(raw)] = outcome.matched
        else:
            unresolved.append((raw, outcome))

    return resolved, unresolved
