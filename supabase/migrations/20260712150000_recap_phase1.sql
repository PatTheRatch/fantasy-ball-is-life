create extension if not exists pgcrypto;

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'display_name', split_part(new.email, '@', 1))
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

create table public.leagues (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique check (slug = lower(slug)),
  name text not null,
  logo_url text,
  accent_color text not null default '#e03131',
  visibility text not null default 'public'
    check (visibility in ('public', 'private')),
  recap_voice text not null default
    'Professional sports journalism with witty, friendly trash talk.',
  owner_user_id uuid references auth.users(id) on delete set null,
  admin_user_id uuid references auth.users(id) on delete set null,
  espn_league_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.league_memberships (
  league_id uuid not null references public.leagues(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'admin', 'member')),
  created_at timestamptz not null default now(),
  primary key (league_id, user_id)
);

create table public.league_week_snapshots (
  id uuid primary key default gen_random_uuid(),
  league_id uuid not null references public.leagues(id) on delete cascade,
  season integer not null check (season >= 2000),
  week integer not null check (week > 0),
  version integer not null check (version > 0),
  captured_at timestamptz not null default now(),
  schema_version text not null,
  matchups_json jsonb not null default '[]'::jsonb,
  standings_json jsonb not null default '[]'::jsonb,
  power_rankings_json jsonb not null default '[]'::jsonb,
  transactions_json jsonb not null default '[]'::jsonb,
  season_stats_json jsonb not null default '[]'::jsonb,
  award_candidates_json jsonb not null default '[]'::jsonb,
  data_quality_json jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  unique (league_id, season, week, version)
);

create table public.recap_editions (
  id uuid primary key default gen_random_uuid(),
  league_id uuid not null references public.leagues(id) on delete cascade,
  season integer not null check (season >= 2000),
  week integer not null check (week > 0),
  version integer not null check (version > 0),
  snapshot_id uuid not null references public.league_week_snapshots(id),
  status text not null default 'draft'
    check (status in ('draft', 'published', 'superseded')),
  structured_content_json jsonb not null,
  data_warnings_json jsonb not null default '[]'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  published_at timestamptz,
  unique (league_id, season, week, version)
);

create index league_week_snapshots_lookup_idx
  on public.league_week_snapshots (league_id, season, week, version desc);

create index recap_editions_lookup_idx
  on public.recap_editions (league_id, season, week, version desc);

create unique index recap_editions_one_published_idx
  on public.recap_editions (league_id, season, week)
  where status = 'published';

insert into public.leagues (
  id,
  slug,
  name,
  visibility,
  espn_league_id
) values (
  '38538700-0000-4000-8000-000000000001',
  'patriot-games',
  'Patriot Games',
  'public',
  '3853870'
) on conflict (slug) do nothing;

create or replace function public.is_league_admin(
  target_league_id uuid,
  target_user_id uuid default auth.uid()
) returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.leagues l
    where l.id = target_league_id
      and (
        l.admin_user_id = target_user_id
        or l.owner_user_id = target_user_id
        or exists (
          select 1
          from public.league_memberships m
          where m.league_id = l.id
            and m.user_id = target_user_id
            and m.role in ('owner', 'admin')
        )
      )
  );
$$;

create or replace function public.is_league_member(
  target_league_id uuid,
  target_user_id uuid default auth.uid()
) returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.league_memberships m
    where m.league_id = target_league_id
      and m.user_id = target_user_id
  );
$$;

create or replace function public.publish_recap_edition(
  target_edition_id uuid,
  actor_user_id uuid
) returns public.recap_editions
language plpgsql
security definer
set search_path = public
as $$
declare
  selected public.recap_editions;
begin
  select *
    into selected
    from public.recap_editions
   where id = target_edition_id
   for update;

  if selected.id is null then
    raise exception 'Recap edition not found';
  end if;

  if not public.is_league_admin(selected.league_id, actor_user_id) then
    raise exception 'Admin access required' using errcode = '42501';
  end if;

  update public.recap_editions
     set status = 'superseded'
   where league_id = selected.league_id
     and season = selected.season
     and week = selected.week
     and status = 'published'
     and id <> selected.id;

  update public.recap_editions
     set status = 'published',
         published_at = now()
   where id = selected.id
   returning * into selected;

  return selected;
end;
$$;

alter table public.profiles enable row level security;
alter table public.leagues enable row level security;
alter table public.league_memberships enable row level security;
alter table public.league_week_snapshots enable row level security;
alter table public.recap_editions enable row level security;

create policy "Profiles are readable by their owner"
  on public.profiles for select
  using (id = auth.uid());

create policy "Profiles are editable by their owner"
  on public.profiles for update
  using (id = auth.uid())
  with check (id = auth.uid());

create policy "Public or joined leagues are readable"
  on public.leagues for select
  using (visibility = 'public' or public.is_league_member(id));

create policy "Memberships are readable by member or admin"
  on public.league_memberships for select
  using (
    user_id = auth.uid()
    or public.is_league_admin(league_id)
  );

create policy "Published recap snapshots are readable"
  on public.league_week_snapshots for select
  using (
    public.is_league_admin(league_id)
    or exists (
      select 1
      from public.recap_editions e
      join public.leagues l on l.id = e.league_id
      where e.snapshot_id = league_week_snapshots.id
        and e.status = 'published'
        and (
          l.visibility = 'public'
          or public.is_league_member(l.id)
        )
    )
  );

create policy "Published recap editions are readable"
  on public.recap_editions for select
  using (
    public.is_league_admin(league_id)
    or (
      status = 'published'
      and exists (
        select 1
        from public.leagues l
        where l.id = recap_editions.league_id
          and (
            l.visibility = 'public'
            or public.is_league_member(l.id)
          )
      )
    )
  );

revoke all on function public.publish_recap_edition(uuid, uuid) from public;
grant execute on function public.publish_recap_edition(uuid, uuid) to service_role;
grant execute on function public.is_league_admin(uuid, uuid) to anon, authenticated, service_role;
grant execute on function public.is_league_member(uuid, uuid) to anon, authenticated, service_role;
