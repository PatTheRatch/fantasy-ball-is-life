"""D-01 — the synthetic projection fixture and its V1 adapter.

Scope note: this file asserts the *artifact*, not the draft engine. No draft code
exists on V2 yet (``git ls-files backend/draft/`` is empty), so nothing here
un-skips anything. The 20 V1 tests that skip on ``BBM_Projections.xls`` un-skip
in D-03…D-06 as each module lands. Carrying "un-skips 20 tests" into this bite as
an exit criterion would silently force the whole port into one PR.

What is being proven here:

1. The committed CSV conforms to ``projection_rows`` (schema §05) — makes AND
   attempts, no bare percentage, keyed on ``player_id``.
2. The generator is deterministic; the committed file is a fresh build.
3. The pool is non-degenerate. This is the assertion that protects D-02: a
   fixture with no spread produces goldens the optimizer satisfies trivially, so
   the characterization oracle would prove nothing.
4. The V1 adapter reproduces V1's exact column contract and the
   ``fg% == fgm/fga`` identity that makes the projection lossless in one
   direction.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tests.fixtures.projections import build_synthetic as build
from tests.fixtures.projections import v1_adapter as adapter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "projections"
CANONICAL_CSV = FIXTURE_DIR / "synthetic_projections.csv"


@pytest.fixture(scope="module")
def raw_rows() -> list[dict[str, str]]:
    with CANONICAL_CSV.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_fixture_file_is_committed() -> None:
    """The whole point of §6.1 is that the input is checked in. If this file is
    missing, every downstream draft test is either skipped or depends on a
    gitignored spreadsheet again."""
    assert CANONICAL_CSV.exists(), f"{CANONICAL_CSV} is not committed"


def test_has_roughly_two_hundred_players(raw_rows: list[dict[str, str]]) -> None:
    # §6.1 asks for "~200 players". Enough for the optimizer to meet real
    # scarcity against a 13-man roster; small enough to review in a diff.
    assert 190 <= len(raw_rows) <= 210, f"expected ~200 rows, got {len(raw_rows)}"


def test_columns_match_projection_rows(raw_rows: list[dict[str, str]]) -> None:
    """Every canonical column is present, and nothing extra crept in."""
    assert list(raw_rows[0].keys()) == list(build.COLUMNS)


def test_no_bare_percentage_column() -> None:
    """Schema §05's normative rule: "makes AND attempts, never a bare
    percentage."

    This is the test that stops the fixture from quietly regressing to V1's
    derived shape. A ``fg%``/``ft%`` column here would bake a §05 violation into
    the repo permanently, and V1 → V2 cannot recover attempts from it.
    """
    offenders = [
        column
        for column in build.COLUMNS
        if "%" in column or column.lower().endswith("_pct")
    ]
    assert offenders == [], f"bare percentage columns present: {offenders}"


def test_both_makes_and_attempts_present() -> None:
    """The makes/attempts pairing is what makes the projection lossless going
    down to V1. Missing one half breaks the adapter's derivation."""
    required = {"fgm", "fga", "ftm", "fta", "tpm", "tpa"}
    assert required <= set(build.COLUMNS)


def test_keyed_on_player_id_never_a_name() -> None:
    """Schema §05: "Keyed on `player_id`, never a name." Names live only in the
    V1 adapter view, derived rather than stored."""
    assert "player_id" in build.COLUMNS
    assert "Name" not in build.COLUMNS
    assert "name" not in build.COLUMNS


def test_makes_never_exceed_attempts(raw_rows: list[dict[str, str]]) -> None:
    """A physical impossibility, and the fastest way to catch a generator bug
    that would otherwise surface as an optimizer oddity much later."""
    for row in raw_rows:
        pid = row["player_id"]
        assert float(row["fgm"]) <= float(row["fga"]) + 1e-9, f"{pid}: fgm > fga"
        assert float(row["ftm"]) <= float(row["fta"]) + 1e-9, f"{pid}: ftm > fta"
        assert float(row["tpm"]) <= float(row["tpa"]) + 1e-9, f"{pid}: tpm > tpa"


def test_player_ids_are_unique(raw_rows: list[dict[str, str]]) -> None:
    ids = [row["player_id"] for row in raw_rows]
    assert len(set(ids)) == len(ids), "duplicate player_id in fixture"


def test_generator_is_deterministic() -> None:
    """Regenerating must be byte-identical. The characterization oracle (D-02)
    records goldens produced from this file; a non-deterministic fixture would
    make those goldens unreproducible and every downstream test flaky."""
    first = build.render(build._build_rows())
    second = build.render(build._build_rows())
    assert first == second, "generator produced different output across runs"


def test_committed_file_matches_a_fresh_build() -> None:
    """The commit must be the generator's output, not a hand-edit.

    A hand-tuned fixture drifts from its generator, and then the D-02 goldens
    describe a file no test can reproduce.
    """
    fresh = build.render(build._build_rows())
    committed = CANONICAL_CSV.read_text()
    assert committed == fresh, (
        "synthetic_projections.csv differs from a fresh build — regenerate it with "
        "`python tests/fixtures/projections/build_synthetic.py` rather than editing it"
    )


# --- Non-degeneracy ----------------------------------------------------------
#
# These are the assertions that give D-02 its value. If the pool has no spread,
# every downstream golden is trivially satisfiable and the oracle certifies
# nothing. Each threshold is a floor, not a target — they exist to catch a
# generator that collapses, not to pin exact values.

MEANINGFUL_SPREAD = {
    "pts": 3.0,
    "reb": 2.0,
    "ast": 1.0,
    "stl": 0.2,
    "blk": 0.3,
    "tpm": 0.6,
    "source_value": 10.0,
}


@pytest.mark.parametrize(("column", "minimum_stdev"), MEANINGFUL_SPREAD.items())
def test_category_has_meaningful_spread(
    raw_rows: list[dict[str, str]], column: str, minimum_stdev: float
) -> None:
    values = [float(row[column]) for row in raw_rows]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stdev = variance**0.5
    assert stdev >= minimum_stdev, (
        f"{column} stdev {stdev:.2f} below {minimum_stdev} — pool too degenerate "
        "for the optimizer to face a real constraint"
    )


def test_shooting_percentages_are_plausible(raw_rows: list[dict[str, str]]) -> None:
    """Derived percentages must land in ranges a real league could produce.

    A generator bug that pushes FG% to 0.20 or 0.95 would still pass every
    structural test while making the fixture useless as an optimizer input.
    """
    for row in raw_rows:
        pid = row["player_id"]
        fga, fgm = float(row["fga"]), float(row["fgm"])
        fta, ftm = float(row["fta"]), float(row["ftm"])
        if fga > 0:
            assert 0.35 <= fgm / fga <= 0.70, f"{pid}: implausible fg% {fgm / fga:.3f}"
        if fta > 0:
            assert 0.50 <= ftm / fta <= 0.95, f"{pid}: implausible ft% {ftm / fta:.3f}"


def test_dollar_ladder_is_right_skewed(raw_rows: list[dict[str, str]]) -> None:
    """Auction values should decay across the ranked pool, not sit flat.

    The optimizer scales by the league's team count and its endgame logic keys
    off cheap players actually existing, so a flat ladder would hide real bugs.
    """
    values = sorted((float(r["source_value"]) for r in raw_rows), reverse=True)
    assert values[0] > values[len(values) // 2] > values[-1], "ladder not monotone"
    assert values[0] >= 40.0, f"top value {values[0]} too low to be a real top pick"


def test_dollar_ladder_reaches_the_one_dollar_floor(raw_rows: list[dict[str, str]]) -> None:
    """The fixture must contain players at exactly $1 — the solver requires it.

    V1's ``optimize_roster`` calls ``_validate_pool_feasibility``, which raises
    unless ``minimum_value_players`` (default **3**) players priced at exactly
    ``$1`` survive filtering::

        ValueError: `minimum_value_players`=3 but only 0 player(s) with $==1
        remain after filtering (minimum_game_threshold=20).

    Found the hard way: the first version of this generator decayed
    exponentially and bottomed out at $1.67, so the fixture parsed fine, passed
    every structural test, and **could not drive the optimizer at all**. That is
    precisely the class of gap D-09 exists to catch, and it would have surfaced
    as a confusing solver error rather than a fixture error.

    Asserts a margin above V1's default so a test may raise
    ``minimum_value_players`` without regenerating the fixture.
    """
    # Mirrors V1's OptimizeLineup default.
    v1_minimum_value_players = 3

    at_floor = sum(1 for r in raw_rows if float(r["source_value"]) == 1.0)
    assert at_floor >= v1_minimum_value_players, (
        f"only {at_floor} player(s) at $1; V1's solver needs at least "
        f"{v1_minimum_value_players} and raises otherwise"
    )
    # Margin, so the fixture is not one V1 default-change away from breaking.
    assert at_floor >= 10, f"$1 floor cluster ({at_floor}) is too thin to be robust"


def test_games_survive_v1_pool_hygiene(raw_rows: list[dict[str, str]]) -> None:
    """Every player must clear V1's real games floor.

    ``clean_player_data()`` drops rows below ``MIN_SEASON_GAMES_FILTER``
    (``backend/config.py``, default **25**). If the fixture's games straddle that
    floor, V1 silently drops players and the D-02 goldens describe a pool smaller
    than the file declares — a discrepancy nobody would notice from the numbers
    alone.

    Pinned to the actual constant's value rather than a guessed round number: an
    earlier version of this test asserted 40, which proved nothing about V1's
    behaviour.
    """
    # Mirrors backend/config.py MIN_SEASON_GAMES_FILTER (default "25").
    v1_min_season_games = 25

    games = [float(row["games"]) for row in raw_rows]
    assert min(games) > v1_min_season_games, (
        f"lowest games value {min(games)} does not clear V1's "
        f"{v1_min_season_games} floor — V1 would drop players the fixture declares"
    )
    # And with margin, not by a hair: a fixture that barely clears the floor is
    # fragile against any future change to the generator's range.
    assert min(games) >= v1_min_season_games + 10, (
        "games floor clearance is too thin to be robust"
    )


# --- The V1 adapter ----------------------------------------------------------


def test_adapter_reproduces_v1_column_contract() -> None:
    """The exact column set V1's loader needs.

    Verified against ``main:backend/draft/optimizer.py``: nine renamed rate
    columns, plus ``Name``/``g``/``Pos``/``$``, plus ``fga/g``/``fta/g`` which
    ``calculate_stats()`` consumes. Missing any one makes V1 drop the row or
    raise.
    """
    assert adapter.V1_COLUMNS == (
        "Name", "g", "Pos", "$", "fga/g", "fta/g",
        "fg%", "ft%", "p/g", "3/g", "r/g", "a/g", "s/g", "b/g", "to/g",
    )


def test_adapter_percentage_is_derived_not_stored() -> None:
    """The load-bearing identity: ``fg% == fgm/fga``.

    This is what makes the projection lossless downward and proves the canonical
    shape is the superset. If the adapter ever carried a percentage independently
    of makes/attempts, the two could disagree and the "one-way, mechanical"
    claim in the module docstring would be false.
    """
    rows = adapter.load_canonical()
    for row in rows:
        v1 = adapter.to_v1(row)
        if row.fga:
            assert v1.fg_pct == pytest.approx(row.fgm / row.fga, abs=1e-9)
        if row.fta:
            assert v1.ft_pct == pytest.approx(row.ftm / row.fta, abs=1e-9)


def test_adapter_emits_every_v1_column_for_every_player() -> None:
    rows = adapter.load_canonical()
    text = adapter.render_v1(rows)
    lines = text.strip().split("\n")
    assert lines[0].split(",") == list(adapter.V1_COLUMNS)
    assert len(lines) == len(rows) + 1
    for line in lines[1:]:
        assert len(line.split(",")) == len(adapter.V1_COLUMNS)


def test_adapter_names_are_unique_and_stable() -> None:
    """V1 merges on ``Name``, so duplicates would silently collapse two players
    into one row. Names are derived, so stability across runs is also required
    for the D-02 goldens to be reproducible."""
    rows = adapter.load_canonical()
    names = [adapter.to_v1(row).name for row in rows]
    assert len(set(names)) == len(names), "adapter produced duplicate names"
    assert names == [adapter.to_v1(row).name for row in rows], "names not stable"


def test_adapter_zero_attempts_does_not_raise() -> None:
    """A zero-attempt player is legitimate and must yield 0.0, not a
    ``ZeroDivisionError``. V1 treats an absent percentage as usable; a crash here
    would make the fixture depend on nobody having a scoreless night."""
    synthetic = adapter.CanonicalRow(
        key="syn-999", name="", position="", games=50.0, minutes_per_game=15.0,
        fgm=0.0, fga=0.0, ftm=0.0, fta=0.0, tpm=0.0, tpa=0.0, tov=1.0,
        pts=0.0, reb=1.0, ast=1.0, stl=0.0, blk=0.0,
        source_value=1.0, injury_status="active",
    )
    v1 = adapter.to_v1(synthetic)
    assert v1.fg_pct == 0.0
    assert v1.ft_pct == 0.0


def test_adapter_value_mapping_is_per_field_correct() -> None:
    """Every V1 rate column must equal its canonical source, field by field.

    This is the gap that mattered: the column *header* test passed, and the
    percentage identity test passed, and neither would catch a transposition
    (``reb=row.ast``) — a row-level mapping bug that would corrupt every D-02
    golden while the whole suite stayed green.

    Pins the entire mapping, not a sample: all 15 columns are asserted for all
    200 rows.
    """
    rows = adapter.load_canonical()
    columns = adapter.to_v1_columns(rows)
    expected = {
        "Name": lambda r: adapter.v1_name(r.key),
        "g": lambda r: r.games,
        "Pos": lambda r: adapter.v1_position(r.key),
        "$": lambda r: r.source_value,
        "fga/g": lambda r: r.fga,
        "fta/g": lambda r: r.fta,
        "fg%": lambda r: r.fgm / r.fga,
        "ft%": lambda r: r.ftm / r.fta,
        "p/g": lambda r: r.pts,
        "3/g": lambda r: r.tpm,
        "r/g": lambda r: r.reb,
        "a/g": lambda r: r.ast,
        "s/g": lambda r: r.stl,
        "b/g": lambda r: r.blk,
        "to/g": lambda r: r.tov,
    }
    assert set(columns) == set(expected)

    for i, row in enumerate(rows):
        for column, getter in expected.items():
            got = columns[column][i]
            want = getter(row)
            assert got == pytest.approx(want) if isinstance(want, float) else got == want, (
                f"row {i} player {row.key}: {column!r} is {got!r}, expected {want!r}"
            )


def test_adapter_columns_are_injectable_as_v1_input() -> None:
    """The delivery mechanism for D-02 is injection, not a file.

    V1's ``OptimizeLineup`` takes a ``projections_df`` argument and prefers it to
    reading ``BBM_PROJECTIONS_PATH`` (which is a hardcoded constant and cannot be
    pointed at anything). So the contract this test locks is: the adapter yields
    every column V1 consumes, with one value per player, in a form a DataFrame
    accepts directly.

    This replaces an earlier test that asserted a written CSV file was
    "V1-consumable" — it was not, because V1's fallback loader is
    ``pd.read_excel``. The old test checked shape and readability and explicitly
    did not check that V1 could read it, so it certified nothing.
    """
    rows = adapter.load_canonical()
    columns = adapter.to_v1_columns(rows)

    assert list(columns) == list(adapter.V1_COLUMNS)
    for name, values in columns.items():
        assert len(values) == len(rows), f"column {name!r} has {len(values)} of {len(rows)}"
    # The types V1's own pipeline expects to see in the frame.
    assert all(isinstance(v, str) for v in columns["Name"])
    assert all(isinstance(v, str) for v in columns["Pos"])
    for numeric in ("g", "$", "fg%", "ft%", "p/g", "r/g", "a/g", "s/g", "b/g", "to/g"):
        assert all(isinstance(v, (int, float)) for v in columns[numeric]), (
            f"column {numeric!r} is not uniformly numeric"
        )


def test_adapter_positions_use_v1_vocabulary() -> None:
    """Every position label must be one V1's solver actually matches.

    V1 validates pool feasibility against exactly ``('C', 'PG', 'SG', 'SF',
    'PF')`` and raises if any has zero eligible players. An earlier version of
    the adapter labelled guards ``'G'`` — which passes every structural test and
    then fails the solver with::

        ValueError: No eligible players remain at position 'PG' after filtering

    Found by running the real solver, which is what D-09's first act was for.
    Locked here so the vocabulary cannot drift back.
    """
    v1_position_vocabulary = {"C", "PG", "SG", "SF", "PF"}

    rows = adapter.load_canonical()
    labels = {adapter.to_v1(row).position for row in rows}
    assert labels <= v1_position_vocabulary, (
        f"positions {sorted(labels - v1_position_vocabulary)} are not in V1's "
        f"vocabulary {sorted(v1_position_vocabulary)}"
    )
    # Each must have at least one eligible player, exactly as V1 checks. 'C' and
    # the four str.contains codes are all exercised by the fixture, not just
    # present in principle.
    for position in v1_position_vocabulary:
        eligible = 0
        for row in rows:
            label = adapter.to_v1(row).position
            # Mirrors V1: C by equality, the rest by substring containment.
            matched = label == "C" if position == "C" else position in label
            if matched:
                eligible += 1
        assert eligible >= 1, (
            f"position {position!r} has 0 eligible players — V1's solver raises on this"
        )


def test_no_network_or_git_access() -> None:
    """§6.1's reason for existing: the fixture must be CI-committable and
    hermetic. If either module imports a client library, the fixture stops being
    a hermetic input and starts depending on the thing it exists to replace."""
    forbidden = ("requests", "httpx", "urllib", "subprocess", "socket")
    for module in (build, adapter):
        source = Path(module.__file__).read_text()  # type: ignore[arg-type]
        for name in forbidden:
            assert f"import {name}" not in source, (
                f"{Path(module.__file__).name} imports {name} — the fixture must "
                "stay hermetic"
            )
