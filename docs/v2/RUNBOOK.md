# Local runbook — clone to a running app

Written by actually running it on a clean checkout (2026-08-23). Every command
below was executed; the "expected output" is what actually printed, not what the
code looks like it should print. The two steps that need Patrick's credentials —
a live Supabase sign-in and a live ESPN sync — are marked as such.

---

## Prerequisites

Pin what the repo needs, not what this machine happens to have:

| Tool | Version | Why |
|---|---|---|
| Python | **3.12** (not 3.11) | `requires-python = ">=3.12"` in `pyproject.toml`. A 3.11 venv fails `pip install` with `Package 'fcp' requires a different Python`. |
| Node | **22** | `ci.yml` pins `node-version: 22`; Vite 8 / React 19 need ≥ 18. |
| Postgres | **16** | `ci.yml` service and the `citext` extension migration target Postgres 16. |

On this VPS `python3` is 3.11.15 but `python3.12` is 3.12.3 — use `python3.12`,
not `python3`:

```bash
python3 --version     # Python 3.11.15  ← NOT this
python3.12 --version  # Python 3.12.3   ← this
node --version        # v22.23.1
```

---

## 1. Clone and checkout

```bash
git clone <repo-url> fantasy-ball-is-life
cd fantasy-ball-is-life
git checkout v2
```

---

## 2. Backend virtualenv

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Expected: pip resolves `fcp` and its dev extras without error. A `python3`
venv fails here with `ERROR: Package 'fcp' requires a different Python: 3.11.15
not in '>=3.12'` — that is the Python-version mistake, not a repo bug.

---

## 3. Database

```bash
docker compose up -d db
```

`docker-compose.yml` runs `postgres:16` as superuser `fcp` / password `fcp` /
database `fcp`, on `:5432`. Migration `0001` runs `CREATE EXTENSION citext`;
`citext` is a trusted extension, so a database-owning role could install it too,
but `fcp` is a superuser here to match the dev/test convention and keep one less
thing to get wrong. This is a local-only database, not a production one.

If a Postgres is already listening on `:5432`, stop it first or the compose
service will fail to bind the port.

---

## 4. Migrations

The database URL lives in the environment, never in `alembic.ini` (its
`sqlalchemy.url` is deliberately empty — `migrations/env.py` reads `DATABASE_URL`):

```bash
source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://fcp:fcp@localhost:5432/fcp"
alembic upgrade head
```

Expected output (nine migrations, in order):

```
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, Baseline: enable the citext extension.
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, Identity tables: users, managers, manager_user_links.
INFO  [alembic.runtime.migration] Running upgrade 0002 -> 0003, fantasy core schema: leagues, seasons, categories, teams, periods.
INFO  [alembic.runtime.migration] Running upgrade 0003 -> 0004, Seed the nine standard scoring categories (platform reference data).
INFO  [alembic.runtime.migration] Running upgrade 0004 -> 0005, Ingestion infrastructure: providers, connections, runs, raw payloads.
INFO  [alembic.runtime.migration] Running upgrade 0005 -> 0006, Lineage columns: ``ingestion_run_id`` on the synced canonical tables.
INFO  [alembic.runtime.migration] Running upgrade 0006 -> 0007, Identity crosswalk: players + provider identities, links, review queue.
INFO  [alembic.runtime.migration] Running upgrade 0007 -> 0008, Matchups + category results (S1-10a).
INFO  [alembic.runtime.migration] Running upgrade 0008 -> 0009, Additive schema constraints (H-05a).
```

Confirm it is at head:

```bash
alembic current
# <hash> (head)
```

---

## 5. Run the backend

The app is a FastAPI **factory** — there is no `backend/api/main.py` and no
module-level `app`, so uvicorn needs `--factory`. Bare `create_app()` wires the
JWKS keyset and the database session from the environment at startup, and fails
fast if any setting is missing or the JWKS cannot be fetched:

```bash
source .venv/bin/activate
export DATABASE_URL="postgresql+psycopg://fcp:fcp@localhost:5432/fcp"
export SUPABASE_JWT_ISSUER="https://<project-ref>.supabase.co/auth/v1"
export SUPABASE_JWT_AUDIENCE="authenticated"
export SUPABASE_JWKS_URL="https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json"
uvicorn backend.api.app:create_app --factory --reload
```

Verify the one genuinely public route:

```bash
curl localhost:8000/health
# {"status":"ok"}
```

`GET /health` is the smoke test that uvicorn reached the app. If the backend
exits at startup instead of listening, a `SUPABASE_*` value or `DATABASE_URL`
is missing or wrong — see §6 and Troubleshooting.

---

## 6. Auth — configure Supabase and get a token

Bare `create_app()` wires the JWKS keyset and the DB session from the
environment (see §5) and verifies JWTs end to end — no mock verifier, no bypass.
The three Supabase settings:

- `SUPABASE_JWT_ISSUER` — the `iss` claim on Supabase tokens, e.g.
  `https://<project-ref>.supabase.co/auth/v1`.
- `SUPABASE_JWT_AUDIENCE` — the `aud` claim, normally `authenticated`.
- `SUPABASE_JWKS_URL` — where the backend fetches signing keys at startup, e.g.
  `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json`.

The verifier accepts **RS256** and **ES256** — Supabase signs ES256 (P-256). The
signature algorithm is derived from the trusted keyset, never the token header,
so a forged `HS256`/`none` header is rejected.

To authenticate, sign in to Supabase Auth for the project and take the access
token, then set it as `VITE_DEV_TOKEN` (see §7). The first authenticated request
creates the `users` row (get-or-create by `auth_subject`) — that is the row
D-03's `--claim-email` needs to exist.

**This sign-in step needs Patrick's Supabase account**, so I could not run it.
The wiring itself is verified against a local fake JWKS: a bad token returns
`401 {"detail":"invalid token"}`, never 500.

Known limitation (out of scope): the keyset is loaded once at startup, so a
Supabase signing-key rotation needs a process restart. Manual and rare, and
there is no deployment yet.

---

## 7. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
```

`frontend/.env.example` has three keys. Set `VITE_DEV_TOKEN` to the Supabase
access token from §6 (the dev auth shim reads it, or `localStorage["fcp.devToken"]`);
leave `VITE_API_PROXY_TARGET=http://localhost:8000` as the default. Without a
token the SPA still serves, but `/` shows "Could not load your profile" — every
authenticated call returns 401 until the token is set.

```bash
npm run dev
```

Vite serves on `http://localhost:5173` and proxies `/api` → `localhost:8000`.
Verified: `curl localhost:5173/` returns `HTTP 200` with `<title>Full Court
Press</title>`.

---

## 8. Sync the league (bootstrap → finalize → claim)

`scripts/sync_league.py` needs the ESPN credentials and the database URL in the
environment (`.env` is gitignored; `.env.example` lists the names):

```bash
export FCP_ESPN_SWID="…"
export FCP_ESPN_ESPN_S2="…"
export FCP_ESPN_LEAGUE_ID="…"
export DATABASE_URL="postgresql+psycopg://fcp:fcp@localhost:5432/fcp"
```

Two-step claim — run without `--claim-team` to list teams, then re-run with one:

```bash
python scripts/sync_league.py --season 2026 --claim-email you@example.com
# Teams (provider id, name, owner):
#      1  Ballers  (owner: Patrick Owner)
#      2  Scorers  (owner: Mike Owner)
# error: --claim-email requires --claim-team

python scripts/sync_league.py --season 2026 --claim-email you@example.com --claim-team 1
```

The summary prints the `league_season_id` URL — that UUID is the only way to
reach the league until S1-11d. The exact numbers below are illustrative (the
*shape* is asserted verbatim by D-03's e2e test, which runs the same pipeline
against a fake adapter):

```
League      Patriot Games  (season 2026)
Teams       12 created
Periods     22 total · 20 finalized · 2 not yet eligible
Matchups    140 persisted · 0 with unknown categories
Runs        league_bootstrap succeeded · finalize succeeded
League URL  http://localhost:5173/leagues/<league_season_id>
```

**This is the one step I could not run live.** The ESPN credentials are
Patrick's, and I did not ask for them. The pipeline itself — bootstrap →
finalize → claim — is verified against a fake adapter by D-03's Postgres tests
(`tests/scripts/test_sync_league_postgres.py`); only the real ESPN fetch is
Patrick-supplied.

---

## Troubleshooting

Failures actually hit while writing this document:

**`pip install -e '.[dev]'` fails with `Package 'fcp' requires a different Python: 3.11.15 not in '>=3.12'`.**
Cause: the venv was created with `python3`, which is 3.11 here. Fix: recreate
with `python3.12 -m venv .venv` and reinstall.

**The backend exits at startup with `required setting SUPABASE_JWKS_URL is not set`** (or any of the four).
Cause: bare `create_app()` fails fast on missing config. Fix: export
`DATABASE_URL` and the three `SUPABASE_*` values before uvicorn (§5).

**`GET /api/v1/me` returns 401 with a real-looking token.**
Cause: the token's `iss`/`aud` don't match `SUPABASE_JWT_ISSUER` /
`SUPABASE_JWT_AUDIENCE`, or the token is expired, or its `kid` is not in the
JWKS (a stale keyset — restart the backend). A bad token is a clean 401, never a 500.

**`alembic upgrade head` says `required setting DATABASE_URL is not set`.**
Cause: `DATABASE_URL` is not exported in the shell running alembic. Fix:
`export DATABASE_URL=…` first (the URL is never in `alembic.ini`).

**`docker compose up -d db` fails to bind `:5432`.**
Cause: another Postgres already owns the port. Fix: stop it, or run the compose
service on a different host port and point `DATABASE_URL` at it.

**`uvicorn` errors with `no module named backend` when run from outside the repo root.**
Cause: the editable install is per-venv; run `uvicorn` from the repo root with
the venv active.
