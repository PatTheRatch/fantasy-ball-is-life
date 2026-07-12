# Supabase recap setup

Supabase is the database + auth layer for the weekly recap newsroom.
This walks through setup from scratch.

## Step 1: Create a Supabase project

1. Go to https://supabase.com and sign in (GitHub login is easiest)
2. Click **"New project"**
3. Pick an organization (default is fine), name it `patriot-games`, set a database password (save it), pick the cheapest region, click **"Create project"**
4. Wait ~2 minutes for the database to provision

## Step 2: Get your keys

In the Supabase dashboard, go to **Project Settings → API**. You need three values:

| Setting | Where to find it | Who sees it |
|---|---|---|
| **Project URL** | `https://xxxxxxxxxxxx.supabase.co` | Needed everywhere |
| **`anon` public key** | Starts with `eyJ...` | Frontend (Vite) |
| **`service_role` secret key** | Starts with `eyJ...` (scroll down) | Backend only. NEVER expose this |

Copy all three somewhere safe. You'll paste them in Step 4.

## Step 3: Run the migration

The migration SQL is at `supabase/migrations/20260712150000_recap_phase1.sql`.
It creates your tables, RLS policies, the publish function, and seeds the Patriot Games league.

### If you installed the Supabase CLI:

```sh
supabase login
supabase link --project-ref <your-project-ref>   # e.g. abcdefghijklm
supabase db push
```

Your project ref is in your Supabase URL: `https://<ref>.supabase.co`

### If you don't have the CLI (simpler):

1. In the Supabase dashboard, go to **SQL Editor** (left sidebar)
2. Click **"New query"**
3. Copy the ENTIRE contents of `supabase/migrations/20260712150000_recap_phase1.sql`
4. Paste it into the SQL editor
5. Click **"Run"** (or Ctrl+Enter)

Verify it worked: in the left sidebar, go to **Table Editor** — you should see `profiles`, `leagues`, `league_memberships`, `league_week_snapshots`, and `recap_editions`. The `leagues` table should have one row: "Patriot Games".

## Step 4: Create your admin user

You need a Supabase auth user so the app knows you're the league admin.

1. In the Supabase dashboard, go to **Authentication → Users** (left sidebar)
2. Click **"Add user" → "Create new user"**
3. Enter your email and a password. Check **"Auto Confirm User"** (skip email verification for now)
4. Click **"Create user"**
5. After the user is created, click on the row to see details — copy the **User UID** (a UUID like `a1b2c3d4-...`)

Now link that user to the Patriot Games league. Go to **SQL Editor**, paste this, replace the UUIDs, and run:

```sql
do $$
declare
  patrick_id uuid := '<paste-your-user-uid-here>';
  patriot_games_id uuid;
begin
  select id into patriot_games_id
  from public.leagues
  where slug = 'patriot-games';

  if patriot_games_id is null then
    raise exception 'Patriot Games league not found — did the migration run?';
  end if;

  insert into public.profiles (id, display_name)
  values (patrick_id, 'Patrick')
  on conflict (id) do update set display_name = excluded.display_name;

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

To verify: in **Table Editor → `league_memberships`**, you should see one row with your user ID and role `owner`.

## Step 5: Configure the app

### Backend (`.env` in `/opt/fantasy-ball-is-life`)

```
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...           # the anon/public key
SUPABASE_SERVICE_ROLE_KEY=eyJ...   # the service_role key — keep secret
PUBLIC_APP_URL=http://100.105.64.94:5173   # or your production URL
RECAP_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...               # server only — keep secret
DEEPSEEK_MODEL=deepseek-v4-flash   # lower-cost Phase 1 test model
```

### Frontend (`frontend/.env`)

```
VITE_SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
VITE_SUPABASE_ANON_KEY=eyJ...     # same anon key — this one IS public
VITE_RECAP_LEAGUE_SLUG=patriot-games
```

## Step 6: Test it

1. Start the backend: `uvicorn backend.api.main:app --host 0.0.0.0 --port 8000`
2. Start the frontend: `cd frontend && npm run dev`
3. Open `http://100.105.64.94:5173/recap`
4. You should see "No published recap for Week X" with an **"Admin mode"** button
5. Click **"Admin mode"** → **"Admin sign in"** → enter your email + password from Step 4
6. You should now see the **"Publishing desk"** with **"Generate Draft"**
7. Enter the week's date range and click **"Generate Draft"**
8. Preview the result, then click **"Publish Draft"**
9. The recap is now live. Click **"Copy Summary"** to get a WhatsApp-ready version

That's it. You now have a working recap newsroom.
