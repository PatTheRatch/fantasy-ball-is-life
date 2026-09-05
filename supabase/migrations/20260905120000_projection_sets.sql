-- Durable storage for projection sets (P-2 framework, currently on-disk parquet).
--
-- Why: ProjectionStore writes parquet under data/projections/, which is
-- gitignored and lives on the container's ephemeral disk. On Render a
-- redeploy or restart wipes it, so an uploaded BBM season set silently
-- disappears and the Draft Room falls back to "no projections active" —
-- with no warning, at the exact moment (draft night) it matters most.
--
-- Shape mirrors the parquet store so the swap is a store-layer change and
-- nothing downstream moves: `projection_sets` is the manifest entry,
-- `projection_set_rows` holds the canonical PlayerProjection rows.
--
-- These tables are GLOBAL, not league-scoped — matching the current store,
-- where the active season/week set is per-install. If projections ever need
-- to be per-league, add a league_id and a unique index per (league, horizon).

create table if not exists public.projection_sets (
    set_id text primary key,                   -- uuid hex, as the store generates
    source text not null,                      -- 'bbm' | 'espn' | 'hashtag' | 'custom'
    horizon text not null check (horizon in ('season', 'week')),
    week int,                                  -- P-6: scopes a week-horizon set
    filename text,
    row_count int not null default 0,
    matched_count int not null default 0,
    unmatched_players jsonb not null default '[]'::jsonb,
    is_active boolean not null default false,
    uploaded_at timestamptz not null default now()
);

-- At most one active set per horizon — the invariant the JSON manifest holds
-- implicitly, enforced here so two concurrent activations cannot both win.
create unique index if not exists projection_sets_one_active_per_horizon
    on public.projection_sets (horizon)
    where is_active;

create index if not exists projection_sets_horizon_uploaded_idx
    on public.projection_sets (horizon, uploaded_at desc);

create table if not exists public.projection_set_rows (
    id bigserial primary key,
    set_id text not null references public.projection_sets(set_id) on delete cascade,

    player_key text not null,                  -- normalize_name() output
    display_name text not null,
    team text,
    positions text[] not null default '{}',

    -- volume
    games double precision,
    minutes_pg double precision,

    -- per-game counting stats
    pts_pg double precision not null default 0,
    reb_pg double precision not null default 0,
    ast_pg double precision not null default 0,
    stl_pg double precision not null default 0,
    blk_pg double precision not null default 0,
    tpm_pg double precision not null default 0,
    to_pg double precision not null default 0,

    -- attempts, so FG%/FT% stay derivable from makes and attempts
    fga_pg double precision not null default 0,
    fta_pg double precision not null default 0,
    fg_pct double precision,
    ft_pct double precision,

    value double precision,                    -- BBM's $ column; drives auction pricing
    injury_status text,
    roster_team text,

    unique (set_id, player_key)
);

create index if not exists projection_set_rows_set_idx
    on public.projection_set_rows (set_id);

-- RLS: readable by anyone (the Draft Room reads projections); writes are
-- service-role only, matching how uploads already reach the backend.
alter table public.projection_sets enable row level security;
alter table public.projection_set_rows enable row level security;

create policy "Anyone can read projection_sets"
    on public.projection_sets
    for select
    using (true);

create policy "Service role can write projection_sets"
    on public.projection_sets
    for all
    to service_role
    using (true)
    with check (true);

create policy "Anyone can read projection_set_rows"
    on public.projection_set_rows
    for select
    using (true);

create policy "Service role can write projection_set_rows"
    on public.projection_set_rows
    for all
    to service_role
    using (true)
    with check (true);
