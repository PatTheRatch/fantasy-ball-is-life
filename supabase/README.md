# Supabase recap setup

The recap newsroom uses Supabase for authentication and persisted weekly
snapshots/editions. FastAPI owns ESPN collection, Anthropic generation, and
publishing. The service-role key must never be exposed to the browser.

## Apply the migration

Install the Supabase CLI, sign in, then run:

```sh
supabase link --project-ref wuzoengojiqotusulwhj
supabase db push
```

For local migration testing:

```sh
supabase start
supabase db reset
```

## Bootstrap Patrick

1. In Supabase Authentication, create Patrick's email/password user.
2. In the SQL editor, replace the email below and run:

```sql
do $$
declare
  patrick_id uuid;
  patriot_games_id uuid;
begin
  select id into patrick_id
  from auth.users
  where lower(email) = lower('patrick@example.com');

  if patrick_id is null then
    raise exception 'Patrick auth user was not found';
  end if;

  insert into public.profiles (id, display_name)
  values (patrick_id, 'Patrick')
  on conflict (id) do update set display_name = excluded.display_name;

  select id into patriot_games_id
  from public.leagues
  where slug = 'patriot-games';

  update public.leagues
  set owner_user_id = patrick_id,
      admin_user_id = patrick_id,
      updated_at = now()
  where id = patriot_games_id;

  insert into public.league_memberships (league_id, user_id, role)
  values (patriot_games_id, patrick_id, 'owner')
  on conflict (league_id, user_id)
  do update set role = excluded.role;
end $$;
```

## Configure the apps

Copy the root and frontend environment examples, then fill in:

- Root `.env`: `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY`, and `RECAP_LEAGUE_SLUG`.
- Frontend `.env`: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and
  `VITE_RECAP_LEAGUE_SLUG`.

Use the project's anon/public key in the frontend. Keep the service-role key
only in the FastAPI environment.
