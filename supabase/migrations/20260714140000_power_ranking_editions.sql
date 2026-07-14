-- Power rankings' AI blurbs, persisted per (league, season, week) so they
-- don't need to be re-asked of the LLM every time the weekly recap is
-- regenerated. One row per week -- once generated, reused as-is; there is no
-- versioning here (contrast league_week_snapshots/recap_editions), since the
-- whole point is "don't redo it."
create table public.power_ranking_editions (
  id uuid primary key default gen_random_uuid(),
  league_id uuid not null references public.leagues(id) on delete cascade,
  season integer not null check (season >= 2000),
  week integer not null check (week > 0),
  ranking_explanations_json jsonb not null default '[]'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique (league_id, season, week)
);

create index power_ranking_editions_lookup_idx
  on public.power_ranking_editions (league_id, season, week);

alter table public.power_ranking_editions enable row level security;

create policy "Power ranking blurbs are readable"
  on public.power_ranking_editions for select
  using (
    public.is_league_admin(league_id)
    or exists (
      select 1
      from public.leagues l
      where l.id = power_ranking_editions.league_id
        and (
          l.visibility = 'public'
          or public.is_league_member(l.id)
        )
    )
  );
