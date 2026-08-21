"""Player-name normalisation and candidate matching.

There is no V1 test file for this — name matching was implemented four times
with four thresholds and two disagreeing normalizers, and none of it was
directly tested. These tests exist because that gap is precisely how players
were silently dropped.
"""

from __future__ import annotations

import pytest

from backend.domain.names import (
    AMBIGUITY_MARGIN,
    FUZZY_FLOOR,
    Candidate,
    match_all,
    match_name,
    normalize_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("LeBron James", "lebron james"),
        ("Nikola Jokić", "nikola jokic"),
        ("Luka Dončić", "luka doncic"),
        ("D'Angelo Russell", "dangelo russell"),
        ("P.J. Tucker", "pj tucker"),
        ("  Extra   Spaces  ", "extra spaces"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalization_cases(raw: str | None, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_hyphens_and_suffixes_survive() -> None:
    """The V1 shadowed normalizer stripped every non-alpha character, so these
    collapsed and could collide with other players. They must be preserved."""
    assert normalize_name("Shai Gilgeous-Alexander") == "shai gilgeous-alexander"
    assert normalize_name("Jaren Jackson Jr.") == "jaren jackson jr"
    assert "-" in normalize_name("Karl-Anthony Towns")


def test_exact_match_is_full_confidence() -> None:
    outcome = match_name("LeBron James", ["lebron james", "kevin durant"])
    assert outcome.matched is not None
    assert outcome.matched.key == "lebron james"
    assert outcome.matched.score == 100.0


def test_accented_source_matches_ascii_pool() -> None:
    outcome = match_name("Nikola Jokić", ["nikola jokic", "nikola vucevic"])
    assert outcome.matched is not None
    assert outcome.matched.key == "nikola jokic"


def test_close_typo_resolves() -> None:
    outcome = match_name("Jayson Tatum", ["jayson tatum"])
    assert outcome.matched is not None


def test_ambiguous_candidates_are_queued_not_guessed() -> None:
    """Charter Decision 18: prefer unknown over confidently wrong."""
    outcome = match_name("Jaylen Brown", ["jalen brown", "jaylin brown"])
    assert outcome.matched is None
    assert outcome.reason == "ambiguous"
    assert len(outcome.candidates) >= 2


def test_no_plausible_candidate_is_queued() -> None:
    outcome = match_name("Completely Different Person", ["lebron james"])
    assert outcome.matched is None
    assert outcome.reason == "low_confidence"


def test_empty_inputs_are_reported_not_crashed() -> None:
    assert match_name(None, ["lebron james"]).reason == "empty_name"
    assert match_name("LeBron James", []).reason == "empty_pool"


def test_unmatched_names_are_returned_never_dropped() -> None:
    """The core behavioural change from V1, which silently discarded them."""
    resolved, unresolved = match_all(
        ["LeBron James", "Totally Unknown Player"], ["lebron james", "kevin durant"]
    )
    assert "lebron james" in resolved
    assert len(unresolved) == 1
    assert unresolved[0][0] == "Totally Unknown Player"
    assert unresolved[0][1].reason is not None


def test_coverage_is_measurable() -> None:
    """A caller can always tell how much of a set actually resolved."""
    names = ["LeBron James", "Kevin Durant", "Nobody At All"]
    resolved, unresolved = match_all(names, ["lebron james", "kevin durant"])
    assert len(resolved) + len(unresolved) == len(names)


def test_fuzzy_confidence_stays_in_its_band() -> None:
    """Fuzzy matches never claim the confidence of an exact or id match."""
    assert Candidate("x", FUZZY_FLOOR).confidence == 0.700
    assert Candidate("x", 100.0).confidence == 0.849
    assert Candidate("x", 85.0).confidence < 0.850


def test_thresholds_are_module_level_data() -> None:
    """One ladder, defined once — not four literals at four call sites."""
    assert FUZZY_FLOOR == 70.0
    assert AMBIGUITY_MARGIN == 5.0
