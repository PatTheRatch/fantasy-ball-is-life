"""The operator entry point: bootstrap → finalize → claim, then print the URL.

This is the composition root, not a layer — ``scripts/`` is outside the
architecture tests, and importing services + repositories directly is correct
here. It ties D-01 (bootstrap) and D-02 (finalize) together and, with
``--claim-email``, performs the D-03 claim that makes a league reachable.

Credentials come from the environment only — never ``argv``. They are live ESPN
session cookies, not config, and ``argv`` is visible in ``ps`` and shell
history. No credential is ever printed, logged, or interpolated into an error.

Usage::

    python scripts/sync_league.py --season 2026 \\
        [--claim-email patrick@example.com --claim-team 1] \\
        [--grace-hours 48] [--skip-finalize]

Requires ``FCP_ESPN_SWID``, ``FCP_ESPN_ESPN_S2``, ``FCP_ESPN_LEAGUE_ID`` and
``DATABASE_URL`` in the environment (see ``.env.example``).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import TextIO

from sqlalchemy.orm import Session

from backend.models.fantasy import League
from backend.platform.db import make_engine, make_session_factory
from backend.platform.settings import SettingsError
from backend.providers.espn.adapter import ESPNAdapter, EspnConnection
from backend.repos.bootstrap import (
    CategoryRepository,
    FantasyTeamRepository,
    FantasyTeamSeasonManagerRepository,
    FantasyTeamSeasonRepository,
    LeagueRepository,
    LeagueSeasonCategoryRepository,
    ManagerRepository,
    MatchupPeriodRepository,
    NbaSeasonRepository,
)
from backend.repos.bootstrap import (
    LeagueSeasonRepository as BootstrapLeagueSeasonRepository,
)
from backend.repos.claim import ClaimRepository, TeamChoice
from backend.repos.ingestion import (
    IngestionRunRepository,
    ProviderRepository,
    RawPayloadRepository,
)
from backend.repos.matchups import (
    LeagueSeasonRepository as ScopedLeagueSeasonRepository,
)
from backend.repos.matchups import (
    MatchupRepository,
)
from backend.repos.scope import LeagueSeasonScope
from backend.services.claim import (
    LeagueClaimService,
    UnknownTeamError,
    UnknownUserError,
)
from backend.services.ingestion import IngestionService
from backend.services.league_bootstrap import (
    PROVIDER_KEY,
    BootstrapError,
    LeagueBootstrapService,
)
from backend.services.matchups import MatchupSyncService

URL_TEMPLATE = "http://localhost:5173/leagues/{league_season_id}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync_league",
        description="Bootstrap, finalize, and (optionally) claim a fantasy league.",
    )
    parser.add_argument(
        "--season", type=int, required=True,
        help="NBA season ending year, e.g. 2026",
    )
    parser.add_argument(
        "--claim-email", metavar="EMAIL",
        help="email of an existing user to claim a team for",
    )
    parser.add_argument(
        "--claim-team", metavar="PROVIDER_TEAM_ID",
        help="provider team id to claim (required with --claim-email)",
    )
    parser.add_argument(
        "--grace-hours", type=int, default=48,
        help="hours after a period's end before it finalizes (default 48)",
    )
    parser.add_argument(
        "--skip-finalize", action="store_true",
        help="bootstrap only; do not finalize periods",
    )
    return parser


def load_config(environ: dict[str, str]) -> tuple[EspnConnection, str]:
    """Read ESPN credentials + database URL from the environment (never argv).

    Follows ``settings._require``: a missing value raises :class:`SettingsError`
    naming the variable — never echoing what was (or was not) found.
    """

    def require(name: str) -> str:
        value = environ.get(name)
        if not value:
            raise SettingsError(f"required setting {name} is not set")
        return value

    conn = EspnConnection(
        league_id=require("FCP_ESPN_LEAGUE_ID"),
        swid=require("FCP_ESPN_SWID"),
        espn_s2=require("FCP_ESPN_ESPN_S2"),
    )
    return conn, require("DATABASE_URL")


def _build_services(session: Session, adapter: object):
    """Wire the bootstrap + sync services (the composition root's job)."""
    ingestion = IngestionService(
        ProviderRepository(session),
        IngestionRunRepository(session),
        RawPayloadRepository(session),
    )
    bootstrap = LeagueBootstrapService(
        ingestion,
        adapter,
        LeagueRepository(session),
        BootstrapLeagueSeasonRepository(session),
        NbaSeasonRepository(session),
        CategoryRepository(session),
        LeagueSeasonCategoryRepository(session),
        FantasyTeamRepository(session),
        FantasyTeamSeasonRepository(session),
        ManagerRepository(session),
        FantasyTeamSeasonManagerRepository(session),
        MatchupPeriodRepository(session),
    )
    return ingestion, bootstrap


def _print_teams(teams: list[TeamChoice], stream: TextIO) -> None:
    print("Teams (provider id, name, owner):", file=stream)
    for team in teams:
        print(
            f"  {team.provider_team_id:>4}  {team.name}  "
            f"(owner: {team.owner_manager})",
            file=stream,
        )


def run(
    session: Session,
    conn: EspnConnection,
    season_year: int,
    *,
    adapter: object | None = None,
    claim_email: str | None = None,
    claim_team: str | None = None,
    grace_hours: int = 48,
    skip_finalize: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the pipeline against ``session``. Returns a process exit code."""
    adapter = adapter or ESPNAdapter()
    out = out or sys.stdout
    err = err or sys.stderr

    ingestion, bootstrap = _build_services(session, adapter)

    # 1. bootstrap
    try:
        boot = bootstrap.bootstrap(conn, season_year)
    except BootstrapError as e:
        print(f"bootstrap failed: {e}", file=err)
        return 1

    season = BootstrapLeagueSeasonRepository(session).find_by_provider(
        PROVIDER_KEY, conn.league_id, season_year
    )
    if season is None:
        print("bootstrap did not produce a league_season", file=err)
        return 1
    season_id = season.id

    # 2. finalize
    fin = None
    if not skip_finalize:
        scope = LeagueSeasonScope(season_id)
        sync = MatchupSyncService(
            ingestion,
            ScopedLeagueSeasonRepository(scope, session),
            MatchupRepository(scope, session),
        )
        fin = sync.finalize_eligible_periods(
            connection=conn, adapter=adapter, grace_hours=grace_hours
        )

    # 3. claim
    claim = None
    if claim_email:
        claim_svc = LeagueClaimService(ClaimRepository(session))
        if claim_team is None:
            _print_teams(claim_svc.list_teams(season_id), err)
            print("error: --claim-email requires --claim-team", file=err)
            return 2
        try:
            claim = claim_svc.claim(season_id, claim_email, claim_team)
        except UnknownUserError as e:
            print(f"claim failed: {e}", file=err)
            return 1
        except UnknownTeamError as e:
            print(f"claim failed: {e}", file=err)
            _print_teams(claim_svc.list_teams(season_id), err)
            return 2

    # 4. summary
    league = session.get(League, season.league_id)
    league_name = league.name if league else "(unknown)"
    scope = LeagueSeasonScope(season_id)
    periods = ScopedLeagueSeasonRepository(scope, session).periods()
    total = len(periods)
    final = sum(1 for p in periods if p.status == "final")
    matchups = MatchupRepository(scope, session).live_for_season()
    unknowns = fin.unknowns if fin is not None else 0

    boot_status = "partial" if boot.unmapped_categories else "succeeded"
    if skip_finalize:
        fin_status = "skipped"
    elif unknowns:
        fin_status = "partial"
    else:
        fin_status = "succeeded"

    print(f"League      {league_name}  (season {season_year})", file=out)
    print(f"Teams       {boot.teams_created} created", file=out)
    print(
        f"Periods     {total} total · {final} finalized · "
        f"{total - final} not yet eligible",
        file=out,
    )
    print(
        f"Matchups    {len(matchups)} persisted · {unknowns} with unknown categories",
        file=out,
    )
    if claim is not None:
        verb = "claimed" if claim.created else "already claimed"
        print(f"Claim       {claim.team_name} by {claim.manager_display_name} ({verb})", file=out)
    print(f"Runs        league_bootstrap {boot_status} · finalize {fin_status}", file=out)
    print(f"League URL  {URL_TEMPLATE.format(league_season_id=season_id)}", file=out)
    return 0


def main(argv: Sequence[str] | None = None, environ: dict[str, str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if environ is None:
        environ = os.environ

    args = build_parser().parse_args(argv)

    try:
        conn, database_url = load_config(environ)
    except SettingsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    engine = make_engine(database_url)
    with make_session_factory(engine)() as session:
        try:
            return run(
                session,
                conn,
                args.season,
                claim_email=args.claim_email,
                claim_team=args.claim_team,
                grace_hours=args.grace_hours,
                skip_finalize=args.skip_finalize,
            )
        except Exception as e:  # noqa: BLE001 — report honestly, never a credential
            print(f"sync failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
