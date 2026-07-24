-- Per-week matchup snapshots.
--
-- league_state_snapshots is a rolling latest-state table (one row per
-- league/season/phase), so its `scoreboard` phase only ever holds the
-- CURRENT week — every past week's matchup view rendered the latest
-- scoreboard. This table keeps one immutable row PER WEEK so the matchup
-- page/tab can show the correct result for any completed week, without a
-- published recap.

create table if not exists public.league_week_scoreboards (
    id uuid primary key default gen_random_uuid(),
    league_id uuid not null references public.leagues(id),
    season int not null,
    week int not null,
    payload_json jsonb not null,
    fetched_at timestamptz not null default now(),
    unique (league_id, season, week)
);

-- RLS: readable by anyone who can see the league (mirrors
-- league_state_snapshots); writable by service role only (the worker).
alter table public.league_week_scoreboards enable row level security;

create policy "Anyone can read league_week_scoreboards for public leagues"
    on public.league_week_scoreboards
    for select
    using (
        exists (
            select 1
            from public.leagues
            where leagues.id = league_week_scoreboards.league_id
              and leagues.visibility = 'public'
        )
    );
