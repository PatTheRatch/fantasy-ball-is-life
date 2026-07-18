-- P-6b: "which team is mine" — members claim their fantasy team in Settings.
-- League Home uses this to surface *your* matchup (spec §8).

alter table public.league_memberships
  add column if not exists team_name text;

-- Members may update their own membership row…
create policy "Members may update their own membership"
  on public.league_memberships
  for update
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- …but only the team_name column. Column-level grants prevent a member from
-- self-promoting `role` through the row-scoped policy above: RLS scopes rows,
-- grants scope columns.
revoke update on public.league_memberships from anon, authenticated;
grant update (team_name) on public.league_memberships to authenticated;
