-- FCP Projections M-1: nba_player_bio (global player identity table).
-- One row per NBA player — DOB, physical measurements, draft info.
-- Shared infrastructure: the Streaming Advisor's enrichment adapter reads this.

create table if not exists public.nba_player_bio (
    id uuid primary key default gen_random_uuid(),
    person_id int not null unique,            -- nba_api NBA person ID
    normalized_name text not null,            -- normalize_name() output
    display_name text not null,               -- as returned by the NBA API
    dob date,
    height text,                              -- e.g. "6-9"
    weight int,                               -- pounds
    draft_year int,
    draft_round int,
    draft_pick int,
    experience int,                            -- seasons played in NBA
    fetched_at timestamptz not null default now()
);

-- RLS: readable by anyone; writable by service role only (the ingest worker).
alter table public.nba_player_bio enable row level security;

create policy "Anyone can read nba_player_bio"
    on public.nba_player_bio
    for select
    using (true);

create policy "Service role can write nba_player_bio"
    on public.nba_player_bio
    for all
    to service_role
    using (true)
    with check (true);
