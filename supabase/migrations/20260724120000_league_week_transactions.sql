-- Per-week transaction snapshots.
--
-- The `transactions` phase in league_state_snapshots is rolling latest-state
-- (one row per league/season/phase), holding only the CURRENT week's
-- transactions. Consumers that want season totals -- the Standings tab's
-- "Moves" and "Trades" columns -- therefore only ever counted one week
-- (~7 adds), and a trade only appeared if it happened during the current
-- week. Trades were effectively invisible all season.
--
-- This table keeps one immutable row PER WEEK so season-cumulative counts
-- are exact, and past weeks are fetched once (a completed week's
-- transactions never change).

create table if not exists public.league_week_transactions (
    id uuid primary key default gen_random_uuid(),
    league_id uuid not null references public.leagues(id),
    season int not null,
    week int not null,
    payload_json jsonb not null,
    fetched_at timestamptz not null default now(),
    unique (league_id, season, week)
);

-- RLS: readable by anyone who can see the league (mirrors
-- league_week_scoreboards); writable by service role only (the worker).
alter table public.league_week_transactions enable row level security;

create policy "Anyone can read league_week_transactions for public leagues"
    on public.league_week_transactions
    for select
    using (
        exists (
            select 1
            from public.leagues
            where leagues.id = league_week_transactions.league_id
              and leagues.visibility = 'public'
        )
    );
