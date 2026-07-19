-- P-4: ESPN credential columns + pgcrypto RPC helpers.
-- espn_league_id already exists on the table (created by recap_phase1 migration);
-- this migration adds the encrypted credential columns and the Supabase-facing
-- encrypt/decrypt RPC wrappers the backend calls.
--
-- BACKGROUND: recap_phase1 (20260712150000) created espn_league_id as text.
-- The backend (credentials.py:133) handles the string→int cast with int(row["espn_league_id"]),
-- so keeping the text column is correct — PostgREST returns it as a string either way.
-- Do NOT alter the column type; the existing seed data ('3853870') and the int() cast
-- work fine together.

alter table public.leagues
  add column if not exists espn_season   integer,
  add column if not exists espn_swid     text,   -- pgp_sym_encrypt(…, 'key')
  add column if not exists espn_s2       text,   -- pgp_sym_encrypt(…, 'key')
  add column if not exists timezone      text default 'America/New_York';

-- ── pgcrypto RPC wrappers ────────────────────────────────────────────
-- The backend calls these via Supabase RPC to encrypt/decrypt ESPN cookies
-- without the key ever touching the database in plaintext (the key lives in
-- the Render CRED_ENCRYPTION_KEY env var and is passed as a parameter).

-- Extension must be in the search path for pgp_sym_encrypt/decrypt to resolve.
-- recap_phase1 already ran "create extension if not exists pgcrypto", but we
-- ensure the schema is accessible for the RPC functions.
alter role authenticator set pgrst.db_schemas = 'public, extensions';

create or replace function public.pgp_sym_encrypt(data text, pwd text)
returns text
language sql
security definer
set search_path = public, extensions
as $$
  select encode(pgp_sym_encrypt(data, pwd, 'compress-algo=1, cipher-algo=aes256'), 'base64');
$$;

create or replace function public.pgp_sym_decrypt(data text, pwd text)
returns text
language sql
security definer
set search_path = public, extensions
as $$
  select pgp_sym_decrypt(decode(data, 'base64'), pwd, 'compress-algo=1, cipher-algo=aes256');
$$;

-- Only the service role may call these — anon users must never encrypt or
-- decrypt credentials.
revoke all on function public.pgp_sym_encrypt(text, text) from public;
revoke all on function public.pgp_sym_decrypt(text, text) from public;
grant execute on function public.pgp_sym_encrypt(text, text) to service_role;
grant execute on function public.pgp_sym_decrypt(text, text) to service_role;

-- ── Service-role RLS (policies from 004) ─────────────────────────────
-- Recap_phase1 already has enable row level security on leagues.

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
