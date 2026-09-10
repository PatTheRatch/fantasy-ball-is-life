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

_POSITION_CYCLE: tuple[str, ...] = ("G", "SG", "SF", "PF", "C")


def v1_name(player_id: str) -> str:
    """Stable display name for a synthetic player.

    ``syn-007`` → ``Synthetic 007``. Stable across runs and unique per player,
    which is all V1's name-keyed merge needs. Deliberately not a real player
    name: the fixture must never be mistaken for real projections.
    """
    suffix = player_id.rsplit("-", 1)[-1]
    return f"Synthetic {suffix}"


def v1_position(player_id: str) -> str:
    """Deterministic position label.

    Derived from the numeric suffix so a given ``player_id`` always reports the
    same position. It is *not* the archetype the generator used — the canonical
    file does not record that, and inventing a lookup would make the adapter
    depend on generator internals. V1 uses ``Pos`` only for display and its
    ``POSITION_OVERRIDES`` hook, so any stable assignment satisfies the contract.
    """
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
        position=v1_position(row.key),
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


def render_v1(rows: list[CanonicalRow]) -> str:
    """Render the V1 view as CSV, header row first."""
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


def write_v1_view(path: Path, rows: list[CanonicalRow] | None = None) -> Path:
    """Emit the V1-consumable file.

    D-01 ships this so D-02 can point ``BBM_PROJECTIONS_PATH`` at a file that
    already exists in V1's shape, keeping D-02 a pure capture step.

    NOTE for D-02: V1 loads via ``pandas.read_excel``. A CSV at that path is
    *not* guaranteed to load. The first thing D-02 must do is confirm which
    format V1's loader actually accepts against ``main`` and, if it insists on
    Excel, convert here (the adapter is the right seam for that) rather than
    changing V1's loader — ``main`` is frozen.

    Writes the CSV form, which is what the D-01 tests assert against. The Excel
    conversion, if required, is D-02's to add at this same seam.
    """
    payload = rows if rows is not None else load_canonical()
    path.write_text(render_v1(payload))
    return path


if __name__ == "__main__":  # pragma: no cover - developer convenience
    out = Path(__file__).with_name("synthetic_projections_v1.csv")
    write_v1_view(out)
    print(f"wrote V1 view to {out}")
