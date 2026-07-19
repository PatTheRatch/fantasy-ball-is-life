-- N-2: league_invites table + self-join + team-claim + member management
--
-- Enables: admins create invite links, users redeem them to join,
-- public-league self-join with team claiming, admin member removal.

-- ── league_invites ────────────────────────────────────────────────────
create table public.league_invites (
  id uuid primary key default gen_random_uuid(),
  league_id uuid not null references public.leagues(id) on delete cascade,
  token text not null unique,  -- random, single-use invite code
  email text,                  -- optional pre-fill for directed invites
  role text not null default 'member' check (role in ('member', 'admin')),
  expires_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  used_by uuid references auth.users(id) on delete set null,
  used_at timestamptz
);

create index league_invites_league_idx on public.league_invites (league_id);
create index league_invites_token_idx on public.league_invites (token) where used_at is null;

alter table public.league_invites enable row level security;

-- Admins can read/create/delete invites for their leagues
create policy "Admins manage their league invites"
  on public.league_invites
  for all
  to authenticated
  using (public.is_league_admin(league_id))
  with check (public.is_league_admin(league_id));

-- ── Self-join INSERT policy ──────────────────────────────────────────
-- Authenticated users may insert themselves (role=member) ONLY into
-- public-visibility leagues. This is how a stranger joins Patriot Games.

drop policy if exists "Members can self-join public leagues" on public.league_memberships;
create policy "Members can self-join public leagues"
  on public.league_memberships
  for insert
  to authenticated
  with check (
    user_id = auth.uid()
    and role = 'member'
    and exists (
      select 1 from public.leagues l
      where l.id = league_memberships.league_id
        and l.visibility = 'public'
    )
  );

-- ── Team-claim uniqueness ────────────────────────────────────────────
-- One team name per league — first claim wins.
drop index if exists league_memberships_team_unique_idx;
create unique index league_memberships_team_unique_idx
  on public.league_memberships (league_id, lower(team_name))
  where team_name is not null;

-- ── Member removal ───────────────────────────────────────────────────
-- Admins can remove members; members can remove themselves.
drop policy if exists "Admins and self can remove members" on public.league_memberships;
create policy "Admins and self can remove members"
  on public.league_memberships
  for delete
  to authenticated
  using (
    user_id = auth.uid()
    or public.is_league_admin(league_id)
  );

-- ── redeem_league_invite RPC ─────────────────────────────────────────
-- Security-definer: validates token (unused, unexpired), inserts
-- membership, marks token used — caller never sees valid tokens.
create or replace function public.redeem_league_invite(p_token text)
returns uuid  -- the league_id of the joined league
language plpgsql
security definer
set search_path = public
as $$
declare
  invite_row public.league_invites;
  caller_id uuid;
begin
  caller_id := auth.uid();
  if caller_id is null then
    raise exception 'Not authenticated';
  end if;

  select *
    into invite_row
    from public.league_invites
   where token = p_token
     and used_at is null
     and (expires_at is null or expires_at > now())
   for update;

  if invite_row.id is null then
    raise exception 'Invalid or expired invite';
  end if;

  -- Insert membership (idempotent: skip if already a member)
  insert into public.league_memberships (league_id, user_id, role)
  values (invite_row.league_id, caller_id, invite_row.role)
  on conflict (league_id, user_id) do nothing;

  -- Mark invite used
  update public.league_invites
     set used_by = caller_id, used_at = now()
   where id = invite_row.id;

  return invite_row.league_id;
end;
$$;

revoke all on function public.redeem_league_invite(text) from public;
grant execute on function public.redeem_league_invite(text) to authenticated;

-- ── Ensure INSERT is granted ──────────────────────────────────────────
-- The membership migration may have narrowed privileges. Restore INSERT
-- so the self-join policy can actually insert rows.
grant insert (league_id, user_id, role, team_name) on public.league_memberships to authenticated;
