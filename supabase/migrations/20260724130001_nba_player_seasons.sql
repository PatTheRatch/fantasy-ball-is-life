-- FCP Projections M-1: nba_player_seasons (global historical stats table).
-- One row per player per season, ~15 seasons back.
-- Stores makes AND attempts (not just percentages) — M-3's model derives
-- percentages from makes/attempts, not the other way around.
-- Shared infrastructure: the Streaming Advisor's enrichment adapter reads this.

create table if not exists public.nba_player_seasons (
    id uuid primary key default gen_random_uuid(),
    person_id int not null,                    -- nba_api NBA person ID
    normalized_name text not null,             -- normalize_name() output
    display_name text not null,                -- as returned by the NBA API
    season int not null,                       -- e.g. 2025 for 2025-26 season
    age float,                                 -- age during that season
    team text,                                 -- team abbreviation
    position text,                             -- e.g. "G", "F", "C", "G-F"

    -- availability
    gp int,                                    -- games played
    gs int,                                    -- games started
    minutes float,                             -- total minutes
    mpg float,                                 -- minutes per game

    -- volume (makes AND attempts — never just percentages)
    fgm float,                                 -- field goals made
    fga float,                                 -- field goals attempted
    ftm float,                                 -- free throws made
    fta float,                                 -- free throws attempted
    tpm float,                                 -- three-pointers made
    tpa float,                                 -- three-pointers attempted
    tov float,                                 -- turnovers
    usg_pct float,                             -- usage percentage

    -- production
    pts float,                                 -- total points
    reb float,                                 -- total rebounds
    ast float,                                 -- total assists
    stl float,                                 -- total steals
    blk float,                                 -- total blocks

    -- context
    team_pace float,                           -- team pace
    team_ortg float,                           -- team offensive rating

    fetched_at timestamptz not null default now(),

    unique (person_id, season)
);

-- RLS: readable by anyone; writable by service role only (the ingest worker).
alter table public.nba_player_seasons enable row level security;

create policy "Anyone can read nba_player_seasons"
    on public.nba_player_seasons
    for select
    using (true);

create policy "Service role can write nba_player_seasons"
    on public.nba_player_seasons
    for all
    to service_role
    using (true)
    with check (true);
