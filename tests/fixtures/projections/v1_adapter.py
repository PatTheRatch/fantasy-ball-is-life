"""One-way adapter: canonical V2 projection rows → V1's column contract.

Why one-way
-----------
``docs/v2/schema/05-projections.md`` requires **makes AND attempts, never a bare
percentage**. V1's ``OptimizeLineup.process_draft_data()`` reads a projections
file whose columns are per-game *rates and percentages*::

    'fg%' -> 'FG%'    'p/g' -> 'PTS'    'r/g' -> 'REB'    's/g' -> 'STL'
    'ft%' -> 'FT%'    '3/g' -> '3PM'    'a/g' -> 'AST'    'b/g' -> 'BLK'
    'to/g' -> 'TO'

plus ``Name``, ``g``, ``Pos``, ``$``, and ``fga/g`` / ``fta/g`` — the last two
because ``calculate_stats()`` derives ``fgm/g = fga/g * FG%``.

That is lossless in one direction and lossy in the other:

* V2 → V1: mechanical. ``fg% = fgm / fga``. No information is invented.
* V1 → V2: impossible. A bare percentage cannot recover makes and attempts.

So the canonical fixture is the superset and this adapter projects *down*. The
projection is never reversed — V2 code must read ``fgm``/``fga``, never ``fg%``
(schema §05: "Consumers read only that shape").

The V1 corpus is the test oracle (charter §9). This adapter is what lets D-02
point ``BBM_PROJECTIONS_PATH`` at the fixture and capture goldens without the
gitignored ``player_rankings/BBM_Projections.xls`` ever being needed again.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from tests.fixtures.projections.build_synthetic import COLUMNS, CSV_NAME
from tests.fixtures.projections.build_synthetic import PlayerRow as CanonicalRow

V1_COLUMNS: tuple[str, ...] = (
    "Name", "g", "Pos", "$", "fga/g", "fta/g",
    "fg%", "ft%", "p/g", "3/g", "r/g", "a/g", "s/g", "b/g", "to/g",
)
"""The V1 column contract, in the order V1's own loader tolerates.

Verified against ``main:backend/draft/optimizer.py``:
``process_draft_data`` renames the nine rate columns, ``clean_player_data``
needs ``Name``/``g``/``$``/``Pos``, and ``calculate_stats`` needs ``fga/g`` and
``fta/g``. All nine renames plus the five structural columns must be present or
V1 drops or crashes on the row.
"""


@dataclass(frozen=True)
class V1Row:
    """A row in V1's shape. ``fg%``/``ft%`` are derived, never carried in the
    canonical file — deriving them here is the whole point of the adapter."""

    name: str
    games: float
    position: str
    dollars: float
    fga_pg: float
    fta_pg: float
    fg_pct: float
    ft_pct: float
    pts: float
    tpm: float
    reb: float
    ast: float
    stl: float
    blk: float
    tov: float


def _safe_div(numerator: float, denominator: float) -> float:
    """Percentage from makes and attempts.

    Zero attempts is a real possibility for a low-minute player and must not
    raise: V1 treats a missing percentage as a value it can work with, and a
    ``ZeroDivisionError`` here would make the fixture depend on nobody having a
    zero-attempt night. Returns 0.0 rather than NaN so the CSV stays numeric and
    V1's pandas read does not introduce a NaN that its own filters treat as
    absent (charter: unknown ≠ zero — but here zero attempts genuinely means the
    player did not shoot, which is a known zero, not an unknown).
    """
    if denominator == 0:
        return 0.0
    return numerator / denominator


# --- Identity projection -----------------------------------------------------
#
# The canonical file carries no name and no position, by design: schema §05 keys
# projection rows on ``player_id`` ("Keyed on `player_id`, never a name"), and
# name resolution belongs to schema §04's ingestion step. V1, however, needs both
# — its loader merges on ``Name`` and filters by ``Pos``.
#
# So the adapter *derives* them from ``player_id`` rather than storing them. This
# keeps the two requirements from contaminating each other: the canonical
# artifact stays schema-pure, and V1 still gets a stable, unique, human-readable
# name it can join on. Deriving rather than storing also means the mapping cannot
# drift out of sync with the fixture.

_POSITION_CYCLE: tuple[str, ...] = ("PG", "SG", "SF", "PF", "C")
"""V1's position vocabulary, for the unknown-player fallback only.

Must stay exactly V1's set — see ``position_for_stats`` for why ``'G'`` is not
a member. ``C`` is last because V1 caps centers at 3 and matches them by exact
equality (``Pos == 'C'``), so it is the one label that cannot be used freely.
"""


def v1_name(player_id: str) -> str:
    """Stable display name for a synthetic player.

    ``syn-007`` → ``Synthetic 007``. Stable across runs and unique per player,
    which is all V1's name-keyed merge needs. Deliberately not a real player
    name: the fixture must never be mistaken for real projections.
    """
    suffix = player_id.rsplit("-", 1)[-1]
    return f"Synthetic {suffix}"


def position_for_stats(reb: float, ast: float, blk: float, tpm: float) -> str:
    """Infer a plausible position label from a row's stat shape.

    **The vocabulary is fixed by V1, not by taste.** ``optimize_roster`` builds
    position constraints from exactly ``('C', 'PG', 'SG', 'SF', 'PF')`` and
    validates that each one has at least one eligible player:

        for position in ('C', 'PG', 'SG', 'SF', 'PF'):
            available = int(player_data_df['Pos'].str.contains(position).sum())
            if available < 1: raise ValueError(...)

    and the solver constraints are:

        'C':  Pos == 'C'               (min 1, max 3)
        'PG': Pos.str.contains('PG')   (min 1)
        'SG': Pos.str.contains('SG')   (min 1)
        'SF': Pos.str.contains('SF')   (min 1)
        'PF': Pos.str.contains('PF')   (min 1)

    Two consequences an earlier version of this function got wrong:

    1. ``'G'`` is **not** a position to V1. It appears in the loop as ``'PG'``,
       and ``str.contains('PG')`` does not match ``'G'`` — so a fixture labelling
       its guards ``'G'`` fails pool feasibility with "No eligible players remain
       at position 'PG'". Guards must be ``'PG'`` or ``'SG'``.
    2. ``'SF'`` is matched by ``str.contains``, so ``'PF'`` must not be a
       substring of an SF label and vice versa. The labels below are all
       distinct two-letter codes, so that holds.

    Ordering is most-distinctive-signature-first. Thresholds are loose on
    purpose: this labels a synthetic fixture, so the bar is "a big is not called
    a guard", not a real position classifier. Pure function of the stats, so a
    label can never disagree with the numbers it came from.
    """
    if blk >= 1.2 and reb >= 7.0:
        return "C"
    if reb >= 6.5:
        return "PF"
    if ast >= 3.5 and tpm >= 1.8:
        return "PG"
    if ast >= 2.8 or tpm >= 2.0:
        return "SG"
    return "SF"


def v1_position(player_id: str) -> str:
    """Kept for callers that only have a player id.

    The honest mapping needs the row's stats, so this indirection exists only so
    ``player_id``-keyed call sites don't break. Prefer
    ``position_for_stats`` — a label derived from an id is exactly the arbitrary
    assignment this module moved away from. Looks up the canonical row and
    delegates; falls back to the id-derived cycle only if the player is unknown.
    """
    rows = load_canonical()
    for row in rows:
        if row.key == player_id:
            return position_for_stats(reb=row.reb, ast=row.ast, blk=row.blk, tpm=row.tpm)
    # Unknown player: stable fallback so the function stays total.
    suffix = player_id.rsplit("-", 1)[-1]
    try:
        index = int(suffix)
    except ValueError:  # pragma: no cover - malformed id
        return _POSITION_CYCLE[0]
    return _POSITION_CYCLE[index % len(_POSITION_CYCLE)]


def to_v1(row: CanonicalRow) -> V1Row:
    """Project one canonical row onto V1's contract.

    Per-game conversion: the canonical row stores per-game rates already, so no
    scaling happens here. ``games`` passes through untouched and is used by V1
    for season aggregation and its ``MIN_SEASON_GAMES_FILTER`` pool hygiene.
    """
    return V1Row(
        name=v1_name(row.key),
        games=row.games,
        position=position_for_stats(reb=row.reb, ast=row.ast, blk=row.blk, tpm=row.tpm),
        dollars=row.source_value,
        fga_pg=row.fga,
        fta_pg=row.fta,
        fg_pct=_safe_div(row.fgm, row.fga),
        ft_pct=_safe_div(row.ftm, row.fta),
        pts=row.pts,
        tpm=row.tpm,
        reb=row.reb,
        ast=row.ast,
        stl=row.stl,
        blk=row.blk,
        tov=row.tov,
    )


def load_canonical(path: Path | None = None) -> list[CanonicalRow]:
    """Read the committed fixture back into canonical rows.

    Kept here (rather than in the test) so the adapter and its consumer share one
    reader — a second parser in the test would let the two drift.
    """
    target = path or Path(__file__).with_name(CSV_NAME)
    rows: list[CanonicalRow] = []
    with target.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(COLUMNS) - set(reader.fieldnames or [])
        if missing:  # pragma: no cover - conformance test covers this
            raise ValueError(f"fixture is missing canonical columns: {sorted(missing)}")
        for record in reader:
            rows.append(
                CanonicalRow(
                    key=record["player_id"],
                    name="",  # not in the canonical file; see below
                    position="",
                    games=float(record["games"]),
                    minutes_per_game=float(record["minutes_per_game"]),
                    fgm=float(record["fgm"]),
                    fga=float(record["fga"]),
                    ftm=float(record["ftm"]),
                    fta=float(record["fta"]),
                    tpm=float(record["tpm"]),
                    tpa=float(record["tpa"]),
                    tov=float(record["tov"]),
                    pts=float(record["pts"]),
                    reb=float(record["reb"]),
                    ast=float(record["ast"]),
                    stl=float(record["stl"]),
                    blk=float(record["blk"]),
                    source_value=float(record["source_value"]),
                    injury_status=record["injury_status"],
                )
            )
    return rows


def to_v1_columns(rows: list[CanonicalRow] | None = None) -> dict[str, list[object]]:
    """Project canonical rows into V1's columns as a plain dict-of-lists.

    **This is the interface D-02 should use.** V1's ``OptimizeLineup`` accepts a
    ``projections_df`` argument (``optimizer.py`` line 91) and uses it in
    preference to reading a file at all::

        if self._projections_df is not None:
            stats_df = self._projections_df.copy()
        else:
            stats_df = pd.read_excel(BBM_PROJECTIONS_PATH)

    So the fixture reaches V1 by **injection**, not by being written to disk.
    That matters, and it is why this function returns a dict rather than a path:

    * ``BBM_PROJECTIONS_PATH`` is a hardcoded constant, not env-overridable — you
      cannot point it anywhere. The original scope line "point
      ``BBM_PROJECTIONS_PATH`` at it" was not achievable.
    * V1's fallback path is ``pd.read_excel``, so a CSV at that path would not
      load. Emitting ``.xlsx`` instead would drag pandas + openpyxl into V2's
      dependency list for a test fixture, which is a bad trade for a greenfield
      rebuild that currently depends on neither.
    * Injection is also strictly more hermetic: no temp files, no filesystem
      state, no format question.

    Returns a dict of column name → list of values, which pandas turns into a
    DataFrame in one call. Returning a dict keeps pandas out of *this* module so
    the fixture stays importable without it; D-02 constructs the DataFrame.
    """
    payload = rows if rows is not None else load_canonical()
    columns: dict[str, list[object]] = {name: [] for name in V1_COLUMNS}
    for row in payload:
        v1 = to_v1(row)
        columns["Name"].append(v1.name)
        columns["g"].append(v1.games)
        columns["Pos"].append(v1.position)
        columns["$"].append(v1.dollars)
        columns["fga/g"].append(v1.fga_pg)
        columns["fta/g"].append(v1.fta_pg)
        columns["fg%"].append(v1.fg_pct)
        columns["ft%"].append(v1.ft_pct)
        columns["p/g"].append(v1.pts)
        columns["3/g"].append(v1.tpm)
        columns["r/g"].append(v1.reb)
        columns["a/g"].append(v1.ast)
        columns["s/g"].append(v1.stl)
        columns["b/g"].append(v1.blk)
        columns["to/g"].append(v1.tov)
    return columns


def render_v1(rows: list[CanonicalRow]) -> str:
    """Render the V1 view as CSV.

    Exists for reviewability — a committed CSV is diffable in a way a DataFrame
    is not — and for the adapter's own tests. It is **not** the D-02 delivery
    mechanism; see ``to_v1_columns``. Kept as a plain renderer so the column
    contract stays inspectable by eye.
    """
    lines: list[str] = [",".join(V1_COLUMNS)]
    for row in rows:
        v1 = to_v1(row)
        cells = (
            v1.name,
            f"{v1.games:.2f}",
            v1.position,
            f"{v1.dollars:.2f}",
            f"{v1.fga_pg:.3f}",
            f"{v1.fta_pg:.3f}",
            f"{v1.fg_pct:.4f}",
            f"{v1.ft_pct:.4f}",
            f"{v1.pts:.3f}",
            f"{v1.tpm:.3f}",
            f"{v1.reb:.3f}",
            f"{v1.ast:.3f}",
            f"{v1.stl:.3f}",
            f"{v1.blk:.3f}",
            f"{v1.tov:.3f}",
        )
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"
