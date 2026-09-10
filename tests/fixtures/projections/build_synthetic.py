"""Deterministic generator for the synthetic projection fixture.

Why this exists
---------------
The draft engine (optimizer, plan diversity, MC targets, Forge Value) has never
had CI coverage: its only real input was ``player_rankings/BBM_Projections.xls``,
which is gitignored and cannot be committed. Twenty V1 tests skip when that file
is absent. ``V1_CLASSIFICATION.md`` §6.1 makes a committed synthetic fixture the
first precondition for porting any of it.

Shape
-----
Output is the canonical V2 row shape from ``docs/v2/schema/05-projections.md``
(``projection_rows``): **makes AND attempts, never a bare percentage.**

This is a deliberate choice over V1's column shape. V1's ``calculate_stats()``
already requires ``fga/g`` and ``fta/g`` and derives ``fgm/g = fga/g * FG%`` — so
V1 carries attempts alongside percentages too. The bare percentage is the derived,
lossy view. Committing a percentage-only fixture would bake a schema §05
violation into the repo permanently, and V2 → V1 is lossless while V1 → V2 is
not. Canonical must be the superset; ``v1_adapter.py`` projects it down.

Determinism
-----------
Everything derives from ``SEED``. Regenerating yields a byte-identical file, so
the fixture is reviewable in a diff and the characterization oracle (D-02) is
reproducible. No ``random``, no clock, no environment input.

Usage
-----
    python tests/fixtures/projections/build_synthetic.py          # write the CSV
    python tests/fixtures/projections/build_synthetic.py --check  # assert unchanged
"""

from __future__ import annotations

import argparse
import hashlib
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

# --- Constants ---------------------------------------------------------------

SEED = 20260
"""Fixed. Changing this regenerates every fixture value and invalidates D-02's
goldens, so it is a versioned part of the oracle, not a knob."""

PLAYER_COUNT = 200
"""~200 players, per §6.1. Large enough that the optimizer hits real feasibility
edges (roster_size 13 from a 200-player pool leaves genuine scarcity) and small
enough to review in a diff."""

TEAM_COUNT = 14
"""A plausible league size. The optimizer scales auction dollars by the live
league's team count, so the fixture's dollar values are computed against this."""

ROSTER_SIZE = 13
"""Matches the §6.1 framing ("~200 players", 13 roster spots) and the benchmark
in docs/specs/DRAFT_ROOM_REVIEW.md ("564-player pool, 13 roster spots")."""

GAMES_RANGE = (48.0, 82.0)
"""Season games played. Must stay above V1's ``MIN_SEASON_GAMES_FILTER`` or the
player is silently dropped by ``clean_player_data()`` and the fixture's usable
pool shrinks without any test noticing."""

MINUTES_RANGE = (14.0, 36.5)
"""Per-game minutes. Drives volume; the spread creates the per-game→season
aggregate structure the optimizer actually solves over."""

CSV_NAME = "synthetic_projections.csv"


# --- Position archetypes -----------------------------------------------------
#
# Realistic distributions matter: a degenerate pool (all players identical, or
# nobody above replacement level) makes the optimizer's feasibility checks
# trivially satisfiable and the D-02 goldens worthless. Each archetype sets the
# mean rate the generator samples around, so bigs really do out-rebound guards
# and the fixture exercises the scarcity the solver exists to handle.


@dataclass(frozen=True)
class Archetype:
    """Mean per-game rates for one position group.

    Rates are *per game*. Volume stats (pts/reb/ast/stl/blk/tov/tpm) scale with
    minutes; the shooting percentages are independent draws, because a big who
    plays more minutes does not shoot a higher percentage.
    """

    key: str
    weight: float
    minutes: tuple[float, float]
    fg_pct: tuple[float, float]
    ft_pct: tuple[float, float]
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    tpm: float
    tov: float
    fga: float  # attempts per game at archetype-minutes; scaled by minutes below
    fta: float


ARCHETYPES: tuple[Archetype, ...] = (
    # weights sum to 1.0. A 14-team league rosters ~70-90 players, so the
    # fixture deliberately holds more replacement-level bodies than starters —
    # that is what makes the endgame picks a real constraint.
    Archetype(
        key="G", weight=0.30, minutes=(20.0, 36.0), fg_pct=(0.400, 0.480),
        ft_pct=(0.780, 0.900), pts=17.0, reb=3.6, ast=4.6, stl=1.1, blk=0.3,
        tpm=2.2, tov=1.7, fga=13.0, fta=3.2,
    ),
    Archetype(
        key="SG", weight=0.16, minutes=(19.0, 35.0), fg_pct=(0.420, 0.495),
        ft_pct=(0.790, 0.905), pts=16.0, reb=3.9, ast=3.1, stl=1.0, blk=0.3,
        tpm=2.4, tov=1.5, fga=12.5, fta=3.0,
    ),
    Archetype(
        key="SF", weight=0.16, minutes=(20.0, 36.0), fg_pct=(0.440, 0.510),
        ft_pct=(0.760, 0.880), pts=15.5, reb=5.4, ast=3.0, stl=1.0, blk=0.5,
        tpm=1.8, tov=1.5, fga=11.5, fta=3.4,
    ),
    Archetype(
        key="PF", weight=0.19, minutes=(18.0, 34.0), fg_pct=(0.470, 0.560),
        ft_pct=(0.680, 0.810), pts=13.5, reb=7.6, ast=2.2, stl=0.7, blk=0.9,
        tpm=1.1, tov=1.4, fga=10.0, fta=3.6,
    ),
    Archetype(
        key="C", weight=0.19, minutes=(17.0, 33.0), fg_pct=(0.500, 0.620),
        ft_pct=(0.620, 0.780), pts=12.5, reb=9.2, ast=1.9, stl=0.6, blk=1.4,
        tpm=0.5, tov=1.5, fga=9.0, fta=3.8,
    ),
)


# --- Generation --------------------------------------------------------------


@dataclass(frozen=True)
class PlayerRow:
    """One canonical ``projection_rows`` row, pre-keying.

    ``key`` is the synthetic stable identifier; it becomes ``player_id`` in the
    CSV. Names live only in the V1 adapter view — V2 forbids name-keying.
    """

    key: str
    # ``name`` and ``position`` are scratch fields, NOT canonical output: neither
    # is serialised (see ``COLUMNS``) and ``load_canonical`` reads both back as
    # "". They exist only for generator-internal readability and debugging. The
    # names/positions a consumer sees are derived in v1_adapter (``v1_name`` from
    # the id, ``position_for_stats`` from the row's stat shape), because the
    # canonical artifact must stay keyed on ``player_id`` with no position column
    # (schema §05). Keeping two schemes in one dataclass is mildly confusing; it
    # is cheaper to say so than to thread a separate debug struct through.
    name: str
    position: str
    games: float
    minutes_per_game: float
    fgm: float
    fga: float
    ftm: float
    fta: float
    tpm: float
    tpa: float
    tov: float
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    source_value: float
    injury_status: str


def _r2(value: float) -> float:
    """Round to 2dp for storage.

    Applied at the end of every field so the committed file is stable and the
    → V1 derivative identities (``fg% == fgm/fga``) hold to a known precision.
    """
    return round(value, 2)


def _r3(value: float) -> float:
    return round(value, 3)


def _sample(rng: random.Random, lo: float, hi: float) -> float:
    """Uniform on [lo, hi]. Uniform keeps the pool evenly spread rather than
    clustering at a mean, which is what the optimizer's scarcity checks need."""
    return rng.uniform(lo, hi)


def _minutes_weight(minutes: float, archetype: Archetype) -> float:
    """Scale volume stats by where the player sits in the archetype's minute band.

    A 14-minute guard does not average the archetype's 17 points. Indexing the
    volume to the minute range is what gives the pool a realistic starter→bench
    gradient; without it every player would look like a 25-minute starter and
    the auction values would have no spread.
    """
    lo, hi = archetype.minutes
    span = hi - lo
    if span <= 0:
        return 1.0
    # 0.55 at the bottom of the band → 1.15 at the top, so volume outruns
    # minutes slightly. Real rotations work this way: higher-minute players are
    # also higher-usage, not merely on the floor longer.
    return 0.55 + 0.60 * ((minutes - lo) / span)


def _build_rows() -> list[PlayerRow]:
    rng = random.Random(SEED)
    rows: list[PlayerRow] = []

    # Assign archetypes by weight, deterministically.
    keys: list[str] = []
    weights = [a.weight for a in ARCHETYPES]
    total = sum(weights)
    cumulative: list[float] = []
    running = 0.0
    for w in weights:
        running += w / total
        cumulative.append(running)

    for _ in range(PLAYER_COUNT):
        draw = rng.random()
        for archetype, boundary in zip(ARCHETYPES, cumulative, strict=True):
            if draw <= boundary:
                keys.append(archetype.key)
                break
        else:  # pragma: no cover - float edge
            keys.append(ARCHETYPES[-1].key)

    by_key = {a.key: a for a in ARCHETYPES}
    # Shuffle, then iterate in shuffled order: players of the same archetype are
    # interleaved through the file rather than clustered in blocks. Without this
    # the fixture's first 60 rows would all be guards, which makes the committed
    # CSV misleading to read (it looks sorted by position and is not) and makes
    # any human spot-check of "the top of the file" examine one archetype only.
    shuffled = list(range(PLAYER_COUNT))
    rng.shuffle(shuffled)

    position_counts: dict[str, int] = {}

    for idx in shuffled:
        archetype = by_key[keys[idx]]
        minutes = _sample(rng, *archetype.minutes)
        weight = _minutes_weight(minutes, archetype)
        games = _sample(rng, *GAMES_RANGE)

        fg_pct = _sample(rng, *archetype.fg_pct)
        ft_pct = _sample(rng, *archetype.ft_pct)

        # Attempts: archetype volume, scaled by the minute weight, with mild
        # jitter so two players at the same minute level are not identical.
        fga_pg = max(1.0, archetype.fga * weight * rng.uniform(0.85, 1.15))
        fta_pg = max(0.2, archetype.fta * weight * rng.uniform(0.80, 1.20))

        # 3PA is a share of FGA; guards take more threes than centers. Cap at
        # 0.75 of attempts so a player cannot make more threes than they take.
        tpa_share = {
            "G": (0.42, 0.60), "SG": (0.40, 0.58), "SF": (0.28, 0.45),
            "PF": (0.14, 0.32), "C": (0.03, 0.18),
        }[archetype.key]
        tpa_pg = fga_pg * rng.uniform(*tpa_share)

        # tpm follows from tpm-rate × 3PA, held below tpa by construction.
        tpm_rate = {
            "G": (0.34, 0.41), "SG": (0.34, 0.42), "SF": (0.31, 0.38),
            "PF": (0.26, 0.35), "C": (0.18, 0.30),
        }[archetype.key]
        tpm_pg = tpa_pg * rng.uniform(*tpm_rate)

        pts_pg = max(1.0, archetype.pts * weight * rng.uniform(0.85, 1.15))
        reb_pg = max(0.2, archetype.reb * weight * rng.uniform(0.85, 1.15))
        ast_pg = max(0.1, archetype.ast * weight * rng.uniform(0.80, 1.20))
        stl_pg = max(0.0, archetype.stl * weight * rng.uniform(0.70, 1.30))
        blk_pg = max(0.0, archetype.blk * weight * rng.uniform(0.70, 1.30))
        tov_pg = max(0.1, archetype.tov * weight * rng.uniform(0.80, 1.20))

        position_counts[archetype.key] = position_counts.get(archetype.key, 0) + 1
        n = position_counts[archetype.key]

        rows.append(
            PlayerRow(
                key=f"syn-{idx + 1:03d}",
                name=f"Synthetic {archetype.key}{n:02d}",
                position=archetype.key,
                games=_r2(games),
                minutes_per_game=_r2(minutes),
                # makes = attempts × percentage; attempts are the source of truth.
                fgm=_r3(fga_pg * fg_pct),
                fga=_r3(fga_pg),
                ftm=_r3(fta_pg * ft_pct),
                fta=_r3(fta_pg),
                tpm=_r3(tpm_pg),
                tpa=_r3(tpa_pg),
                tov=_r3(tov_pg),
                pts=_r3(pts_pg),
                reb=_r3(reb_pg),
                ast=_r3(ast_pg),
                stl=_r3(stl_pg),
                blk=_r3(blk_pg),
                source_value=0.0,  # filled by _assign_source_values
                injury_status="active",
            )
        )

    return _assign_source_values(rows)


def _assign_source_values(rows: list[PlayerRow]) -> list[PlayerRow]:
    """Give each row a ``source_value`` on a V1-comparable dollar scale.

    V1's ``$`` column is a $1..$N auction value. ``source_value`` is the
    canonical home for "the source's own rank/value", so filling it here keeps
    the V1 adapter a pure renaming rather than a computation.
    """
    def fantasy_impact(row: PlayerRow) -> float:
        """A crude 9-cat impact score. Deliberately simple: the fixture only
        needs a monotone ordering to hang dollars off, not a real valuation —
        Forge Value (D-03) is the thing being tested, and it must derive worth
        from the projection rows, not receive it pre-chewed."""
        return (
            row.pts
            + row.reb * 1.2
            + row.ast * 1.5
            + row.stl * 3.0
            + row.blk * 3.0
            - row.tov * 1.5
            + row.tpm * 2.0
        ) * (row.games / 82.0)

    ordered = sorted(rows, key=fantasy_impact, reverse=True)

    # A plausible auction ladder: a top pick runs ~$70 in a 14-team league, and
    # the deep bench settles at the $1 floor. Dollars are an exponential decay
    # across the ranked pool so the distribution is right-skewed like a real
    # auction, rather than linear.
    top, floor = 70.0, 1.0
    decay = 0.977
    dollars: dict[str, float] = {}
    for rank, row in enumerate(ordered):
        value = floor + (top - floor) * math.pow(decay, rank)
        dollars[row.key] = _r2(max(floor, value))

    return [
        PlayerRow(**{**row.__dict__, "source_value": dollars[row.key]})
        for row in rows
    ]


# --- Serialisation -----------------------------------------------------------

COLUMNS: tuple[str, ...] = (
    "player_id", "games", "minutes_per_game",
    "fgm", "fga", "ftm", "fta", "tpm", "tpa", "tov",
    "pts", "reb", "ast", "stl", "blk",
    "source_value", "injury_status",
)
"""Canonical column order. Mirrors ``projection_rows`` in schema §05, minus the
relational keys a fixture has no use for (``id``, ``projection_set_id``), with
the synthetic stable key written as ``player_id``."""


def render(rows: list[PlayerRow]) -> str:
    """Render deterministically. ``lineterminator`` is pinned so the file does
    not change shape between platforms — the byte-identity test depends on it."""
    lines: list[str] = [",".join(COLUMNS)]
    for row in rows:
        values = {
            **row.__dict__,
            "player_id": row.key,
        }
        lines.append(",".join(_format_cell(values[c]) for c in COLUMNS))
    return "\n".join(lines) + "\n"


def _format_cell(value: object) -> str:
    if isinstance(value, float):
        # Two decimals everywhere; the canonical fields are stored at 2-3dp and
        # uniform formatting keeps the diff readable.
        return f"{value:.2f}"
    return str(value)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def write_fixture(path: Path) -> list[PlayerRow]:
    rows = _build_rows()
    path.write_text(render(rows))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed fixture differs from a fresh build",
    )
    args = parser.parse_args(argv)

    target = Path(__file__).with_name(CSV_NAME)

    if args.check:
        fresh = render(_build_rows())
        current = target.read_text() if target.exists() else ""
        if fresh != current:
            print(
                f"FAIL: {target.name} is stale or was edited by hand.\n"
                f"  committed: {digest(current)}\n"
                f"  rebuilt:   {digest(fresh)}\n"
                "Regenerate with: python tests/fixtures/projections/build_synthetic.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {target.name} matches a fresh build ({digest(fresh)})")
        return 0

    rows = write_fixture(target)
    print(
        f"wrote {len(rows)} rows to {target}\n"
        f"digest: {digest(target.read_text())}\n"
        f"seed:   {SEED}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
