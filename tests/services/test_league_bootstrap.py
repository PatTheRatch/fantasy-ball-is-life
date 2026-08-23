"""League bootstrap: the slug derivation (hermetic).

``slugify`` must guarantee lowercase — ``leagues.slug`` carries a
``slug = lower(slug)`` check constraint, so the provider's casing can never
reach the column.
"""

from backend.services.league_bootstrap import slugify


def test_slugify_lowercases() -> None:
    assert slugify("Patriot Games") == "patriot-games"
    assert slugify("  PATRIOT   GAMES  ") == "patriot-games"


def test_slugify_collapses_non_alphanumeric_to_hyphens() -> None:
    assert slugify("Ballers & Co.") == "ballers-co"
    assert slugify("The #1 League!") == "the-1-league"


def test_slugify_falls_back_when_empty() -> None:
    assert slugify("!!!") == "league"
    assert slugify("") == "league"
