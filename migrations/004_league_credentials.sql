-- P-4a: Add ESPN credential columns to leagues table.
-- swid/s2 are encrypted at rest with pgcrypto (symmetric, key from
-- backend env CRED_ENCRYPTION_KEY). Only the service-role key can read
-- the raw text; anon/public access is denied via RLS below.

alter table public.leagues
  add column if not exists espn_league_id bigint,
  add column if not exists espn_season   integer,
  add column if not exists espn_swid     text,   -- pgp_sym_encrypt(…, 'key')
  add column if not exists espn_s2       text,   -- pgp_sym_encrypt(…, 'key')
  add column if not exists timezone      text default 'America/New_York';

-- Service-role access (the backend uses the service_role key for all
-- writes, including decryption). Anon & authenticated users cannot
-- read the encrypted columns.
alter table public.leagues enable row level security;

-- Drop existing policies if re-running (idempotent migration)
drop policy if exists "Service role can read all leagues" on public.leagues;
drop policy if exists "Service role can write leagues" on public.leagues;

create policy "Service role can read all leagues"
  on public.leagues
  for select
  to service_role
  using (true);

create policy "Service role can write leagues"
  on public.leagues
  for all
  to service_role
  using (true);
