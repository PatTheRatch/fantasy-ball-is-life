"""
FCP Projections M-1b — historical backfill from the Kaggle CSV dataset.

stats.nba.com blocks whole IP ranges (UK residential AND VPN egress, as it
turns out), so the one-time historical backfill runs from the Kaggle
"NBA Stats (1947-present)" dataset instead — Basketball-Reference season
tables as CSVs. This module maps them onto the SAME ``nba_player_seasons``
/ ``nba_player_bio`` rows the nba_api ingest writes, through the same
store methods: downstream consumers (reader, backtest, model) cannot tell
the sources apart. nba_api remains the in-season upkeep path.

Source-convention translations handled here (all verified against the
dataset, tested against synthetic fixtures):
  - Season year: the CSVs use the END year (their 2024 = 2023-24 season);
    our schema uses the START year. ``--seasons`` takes OUR convention.
  - USG%: CSVs store 31.2 (a percentage); we store 0.312 (a ratio),
    matching nba_api's USG_PCT.
  - Traded players: the CSVs carry one combined row (``TOT`` / ``2TM``
    style) plus per-team stint rows. The combined row wins, so the
    ``(person_id, season)`` unique key holds.
  - Player IDs: the CSVs key players by Basketball-Reference string ids
    (e.g. ``jamesle01``). We derive a deterministic NEGATIVE synthetic
    ``person_id`` from each (real NBA person ids are positive, so the id
    spaces can never collide), and fail loudly on hash collisions rather
    than silently merging two players. ``normalized_name`` remains the
    cross-source join key.

Bios: the dataset has position and experience but not DOB/height/weight/
draft — bio rows are written with what exists and the report says what
was unavailable. A working nba_api egress can top bios up later; the
season stats (what M-3 actually trains on) are complete.

CLI:
  python -m backend.nbadata.csv_backfill --dir ~/Downloads/nba-stats \
      --seasons 2010-2025 [--dry-run] [--no-bios]

Requires SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY env vars unless --dry-run.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import zlib
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from backend.league.data_feed import normalize_name
from backend.nbadata.ingest import (
    IngestReport,
    _safe_float,
    _safe_int,
    _upsert_player_bios,
    _upsert_player_seasons,
)
from backend.recaps.store import RecapStore

logger = logging.getLogger(__name__)

# Dataset filenames (Kaggle: "NBA Stats (1947-present)").
PER_GAME_FILE = "Player Per Game.csv"
ADVANCED_FILE = "Advanced.csv"
TEAM_SUMMARIES_FILE = "Team Summaries.csv"

# Column aliases — the dataset has renamed columns across versions, so we
# resolve each logical field against a list of candidates and fail with a
# clear message naming what's missing.
_ALIASES: dict[str, list[str]] = {
    "season": ["season"],
    "player_id": ["player_id"],
    "player": ["player", "player_name"],
    "lg": ["lg", "league"],
    "tm": ["tm", "team", "abbreviation"],
    "age": ["age"],
    "pos": ["pos", "position"],
    "experience": ["experience", "exp"],
    "g": ["g", "gp", "games"],
    "gs": ["gs", "games_started"],
    "mp_pg": ["mp_per_game", "mpg", "mp"],
    "fg_pg": ["fg_per_game", "fg"],
    "fga_pg": ["fga_per_game", "fga"],
    "ft_pg": ["ft_per_game", "ft"],
    "fta_pg": ["fta_per_game", "fta"],
    "tp_pg": ["x3p_per_game", "fg3_per_game", "x3p"],
    "tpa_pg": ["x3pa_per_game", "fg3a_per_game", "x3pa"],
    "tov_pg": ["tov_per_game", "tov"],
    "pts_pg": ["pts_per_game", "pts"],
    "trb_pg": ["trb_per_game", "trb", "reb_per_game"],
    "ast_pg": ["ast_per_game", "ast"],
    "stl_pg": ["stl_per_game", "stl"],
    "blk_pg": ["blk_per_game", "blk"],
    "usg_pct": ["usg_percent", "usg_pct"],
    "pace": ["pace"],
    "ortg": ["o_rtg", "ortg", "off_rtg"],
}


class CsvSchemaError(RuntimeError):
    """A required column could not be resolved in a dataset CSV."""


def _col(df: pd.DataFrame, key: str, *, file: str, required: bool = True) -> Optional[str]:
    """Resolve a logical field to the actual column name in ``df``."""
    for candidate in _ALIASES[key]:
        if candidate in df.columns:
            return candidate
    if required:
        raise CsvSchemaError(
            f"{file}: none of {_ALIASES[key]} found for '{key}'. "
            f"Columns present: {sorted(df.columns.tolist())[:40]}"
        )
    return None


def synthetic_person_id(bref_id: str) -> int:
    """Deterministic negative person_id from a Basketball-Reference id.

    Real NBA person ids are positive ints, so negatives guarantee the two
    id spaces never collide. CRC32 is stable across runs and platforms.
    """
    h = zlib.crc32(str(bref_id).encode("utf-8")) & 0x7FFFFFFF
    return -(h or 1)  # never 0


def _is_combined_row(tm: Any) -> bool:
    """True for the multi-team combined row ('TOT', '2TM', '3TM', …)."""
    s = str(tm or "").strip().upper()
    return s == "TOT" or (len(s) == 3 and s.endswith("TM") and s[0].isdigit())


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------


def build_season_rows(
    per_game: pd.DataFrame,
    advanced: pd.DataFrame,
    team_summaries: pd.DataFrame,
    seasons: list[int],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Map dataset frames → nba_player_seasons rows (our conventions).

    ``seasons`` uses OUR start-year convention; the CSVs use end year.
    Returns (rows, errors). Collisions in the synthetic id space raise —
    a silent merge of two players would corrupt the model's training data.
    """
    errors: list[str] = []
    f = PER_GAME_FILE
    c = {k: _col(per_game, k, file=f) for k in (
        "season", "player_id", "player", "tm", "age", "pos", "g",
        "mp_pg", "fg_pg", "fga_pg", "ft_pg", "fta_pg", "tp_pg", "tpa_pg",
        "tov_pg", "pts_pg", "trb_pg", "ast_pg", "stl_pg", "blk_pg",
    )}
    c_gs = _col(per_game, "gs", file=f, required=False)
    c_lg = _col(per_game, "lg", file=f, required=False)

    df = per_game.copy()
    if c_lg:
        df = df[df[c_lg].astype(str).str.upper() == "NBA"]
    # END-year (theirs) → START-year (ours)
    df["_our_season"] = pd.to_numeric(df[c["season"]], errors="coerce") - 1
    df = df[df["_our_season"].isin(seasons)]

    # ---- advanced: usg% per (player_id, csv-season), combined row first --
    usg_map: dict[tuple[str, int], float] = {}
    if not advanced.empty:
        fa = ADVANCED_FILE
        a_season = _col(advanced, "season", file=fa)
        a_pid = _col(advanced, "player_id", file=fa)
        a_tm = _col(advanced, "tm", file=fa, required=False)
        a_usg = _col(advanced, "usg_pct", file=fa, required=False)
        if a_usg:
            adv = advanced.copy()
            if a_tm is not None:
                adv["_combined"] = adv[a_tm].map(_is_combined_row)
                adv = adv.sort_values("_combined", ascending=False)
            for _, r in adv.iterrows():
                key = (str(r[a_pid]), int(r[a_season]))
                if key not in usg_map:
                    v = _safe_float(r[a_usg])
                    if v is not None:
                        usg_map[key] = round(v / 100.0, 4)  # 31.2 → 0.312
        else:
            errors.append(f"{fa}: no usage column — usg_pct will be null")

    # ---- team summaries: (csv-season, team) → pace / ortg ---------------
    pace_map: dict[tuple[int, str], tuple[Optional[float], Optional[float]]] = {}
    if not team_summaries.empty:
        ft_ = TEAM_SUMMARIES_FILE
        t_season = _col(team_summaries, "season", file=ft_)
        t_abbr = _col(team_summaries, "tm", file=ft_)
        t_pace = _col(team_summaries, "pace", file=ft_, required=False)
        t_ortg = _col(team_summaries, "ortg", file=ft_, required=False)
        for _, r in team_summaries.iterrows():
            season_v = _safe_int(r[t_season])
            if season_v is None:
                continue
            pace_map[(season_v, str(r[t_abbr]).upper())] = (
                _safe_float(r[t_pace]) if t_pace else None,
                _safe_float(r[t_ortg]) if t_ortg else None,
            )

    # ---- one row per (player, season): combined row wins ----------------
    df["_combined"] = df[c["tm"]].map(_is_combined_row)
    df = df.sort_values(
        ["_combined", c["g"]], ascending=[False, False]
    ).drop_duplicates(subset=[c["player_id"], "_our_season"], keep="first")

    rows: list[dict[str, Any]] = []
    id_owner: dict[int, str] = {}
    for _, r in df.iterrows():
        bref_id = str(r[c["player_id"]])
        person_id = synthetic_person_id(bref_id)
        owner = id_owner.setdefault(person_id, bref_id)
        if owner != bref_id:
            raise RuntimeError(
                f"Synthetic person_id collision: {owner!r} and {bref_id!r} "
                f"both hash to {person_id}. Refusing to continue — this "
                "needs a different id derivation, not a silent merge."
            )

        our_season = int(r["_our_season"])
        csv_season = our_season + 1
        team = str(r[c["tm"]] or "").upper()
        mpg = _safe_float(r[c["mp_pg"]])
        gp = _safe_int(r[c["g"]])
        pace, ortg = pace_map.get((csv_season, team), (None, None))
        display_name = str(r[c["player"]] or "")

        rows.append({
            "person_id": person_id,
            "normalized_name": normalize_name(display_name),
            "display_name": display_name,
            "season": our_season,
            "age": _safe_float(r[c["age"]]),
            "team": team,
            "position": str(r[c["pos"]]) if pd.notna(r[c["pos"]]) else None,
            "gp": gp,
            "gs": _safe_int(r[c_gs]) if c_gs else None,
            "minutes": round(mpg * gp, 1) if mpg is not None and gp is not None else None,
            "mpg": mpg,
            "fgm": _safe_float(r[c["fg_pg"]]),
            "fga": _safe_float(r[c["fga_pg"]]),
            "ftm": _safe_float(r[c["ft_pg"]]),
            "fta": _safe_float(r[c["fta_pg"]]),
            "tpm": _safe_float(r[c["tp_pg"]]),
            "tpa": _safe_float(r[c["tpa_pg"]]),
            "tov": _safe_float(r[c["tov_pg"]]),
            "usg_pct": usg_map.get((bref_id, csv_season)),
            "pts": _safe_float(r[c["pts_pg"]]),
            "reb": _safe_float(r[c["trb_pg"]]),
            "ast": _safe_float(r[c["ast_pg"]]),
            "stl": _safe_float(r[c["stl_pg"]]),
            "blk": _safe_float(r[c["blk_pg"]]),
            "team_pace": pace,
            "team_ortg": ortg,
        })

    return rows, errors


def build_bio_rows(season_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bio rows from what the dataset offers: position + experience.

    DOB / height / weight / draft aren't in these CSVs — those fields stay
    null and can be topped up by the nba_api bio pass from a working
    egress later. One row per person; latest season wins for position,
    season count stands in for experience.
    """
    by_person: dict[int, dict[str, Any]] = {}
    seasons_per_person: dict[int, int] = {}
    for row in sorted(season_rows, key=lambda r: r["season"]):
        pid = row["person_id"]
        seasons_per_person[pid] = seasons_per_person.get(pid, 0) + 1
        by_person[pid] = {
            "person_id": pid,
            "normalized_name": row["normalized_name"],
            "display_name": row["display_name"],
            "position": row["position"],
            "experience": seasons_per_person[pid],
        }
    return list(by_person.values())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def backfill_from_csv(
    dataset_dir: str | Path,
    seasons: list[int],
    *,
    supabase_url: str | None = None,
    supabase_key: str | None = None,
    include_bios: bool = True,
) -> IngestReport:
    """Build rows from the dataset CSVs and upsert them.

    Dry run (no credentials): rows are built and counted, nothing written.
    """
    dataset_dir = Path(dataset_dir)
    report = IngestReport(seasons_processed=[])

    def _read(name: str, *, required: bool) -> pd.DataFrame:
        path = dataset_dir / name
        if not path.exists():
            if required:
                raise FileNotFoundError(
                    f"{path} not found — point --dir at the unzipped Kaggle "
                    "'NBA Stats (1947-present)' dataset."
                )
            report.errors.append(f"{name} not found — its fields will be null")
            return pd.DataFrame()
        return pd.read_csv(path)

    per_game = _read(PER_GAME_FILE, required=True)
    advanced = _read(ADVANCED_FILE, required=False)
    team_summaries = _read(TEAM_SUMMARIES_FILE, required=False)

    rows, transform_errors = build_season_rows(
        per_game, advanced, team_summaries, seasons
    )
    report.errors.extend(transform_errors)
    report.players_seen = len(rows)
    report.seasons_processed = sorted({r["season"] for r in rows})

    missing = sorted(set(seasons) - set(report.seasons_processed))
    if missing:
        report.errors.append(
            f"No rows in the dataset for requested seasons: {missing} "
            "(remember --seasons uses start-year: 2024 = the 2024-25 season)"
        )

    store: RecapStore | None = None
    if supabase_url and supabase_key:
        store = RecapStore(url=supabase_url, service_role_key=supabase_key)

    if store is None:
        report.rows_written = len(rows)  # dry run: rows built
        logger.info("Dry run: built %d season rows, wrote nothing", len(rows))
        return report

    # Upsert in chunks — one giant POST body risks PostgREST limits.
    written = 0
    for i in range(0, len(rows), 500):
        written += _upsert_player_seasons(
            rows[i : i + 500], store, report_errors=report.errors
        )
    report.rows_written = written

    if include_bios and rows:
        bio_rows = build_bio_rows(rows)
        for i in range(0, len(bio_rows), 500):
            report.bios_written += _upsert_player_bios(
                bio_rows[i : i + 500], store, report_errors=report.errors
            )

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_seasons(spec: str) -> list[int]:
    """'2010-2025' → [2010..2025]; '2024' → [2024]; '2020,2022' → both."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.update(range(int(lo), int(hi) + 1))
        elif part:
            out.add(int(part))
    return sorted(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Backfill nba_player_seasons from the Kaggle CSV dataset",
    )
    parser.add_argument("--dir", required=True, help="Unzipped dataset directory")
    parser.add_argument(
        "--seasons",
        default="2010-2025",
        help="START-year seasons, e.g. '2010-2025' (2025 = the 2025-26 season)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build rows, write nothing")
    parser.add_argument("--no-bios", action="store_true", help="Skip the bio upsert")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not args.dry_run and (not url or not key):
        print(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set "
            "(or pass --dry-run to preview)."
        )
        sys.exit(2)

    report = backfill_from_csv(
        args.dir,
        _parse_seasons(args.seasons),
        supabase_url=None if args.dry_run else url,
        supabase_key=None if args.dry_run else key,
        include_bios=not args.no_bios,
    )

    print()
    print(report)
    for e in report.errors[:20]:
        print("ERROR:", e)
    if report.players_seen == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
