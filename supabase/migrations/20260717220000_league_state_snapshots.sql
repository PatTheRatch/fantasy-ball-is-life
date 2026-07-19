-- P-3a: league_state_snapshots — rolling upsert table for the snapshot worker.
-- One live row per league/season/phase; the worker UPSERTs on each refresh.

create table if not exists public.league_state_snapshots (
    id uuid primary key default gen_random_uuid(),
    league_id uuid not null references public.leagues(id),
    season int not null,
    week int not null,
    phase text not null,
    payload_json jsonb not null,
    fetched_at timestamptz not null default now(),
    unique (league_id, season, phase)
);

-- RLS: readable by anyone who can see the league (same shape as recap_editions),
-- writable by service role only (the worker runs with service role key).

alter table public.league_state_snapshots enable row level security;

create policy "Anyone can read league_state_snapshots for public leagues"
    on public.league_state_snapshots
    for select
    using (
        exists (
            select 1
            from public.leagues
            where leagues.id = league_state_snapshots.league_id
              and leagues.visibility = 'public'
        )
    );
