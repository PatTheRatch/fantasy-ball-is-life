# Local runbook — clone to a running app

Written by actually running it on a clean checkout (2026-08-23). Every command
below was executed; the "expected output" is what actually printed, not what the
code looks like it should print. Where the app does not yet have a running path
(auth), that is stated as a finding, not papered over.

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
module-level `app`, so uvicorn needs `--factory`:

```bash
uvicorn backend.api.app:create_app --factory --reload
```

Verify the one genuinely public route:

```bash
curl localhost:8000/health
# {"status":"ok"}
```

`GET /health` works with no environment and no database — it is the smoke test
that uvicorn reached the app.

---

## 6. Auth — the part that is not wired yet (a finding, not a step to skip)

The backend verifies JWTs end-to-end; there is no bypass and none is added here.
But the path from a real Supabase token to a verified request **does not exist
yet**, for two reasons, both out of scope for a runbook and both needing a code
change:

1. **Nothing wires the app.** `create_app(keyset=…, session_factory=…)` takes the
   JWKS and the DB session as injectable parameters (so tests can build without
   them), but no entry point loads the JWKS from `SUPABASE_JWKS_URL` or builds
   the session from `DATABASE_URL` and passes them in. `uvicorn … --factory`
   therefore produces an app with `jwks_keyset=None` and `session_factory=None`.
   Verified: `GET /api/v1/me` with a bearer token returns **500**, not a clean
   401/200.

2. **The verifier is RS256-only.** `backend/platform/auth.py` calls
   `jwt.decode(…, algorithms=["RS256"])` via `RSAAlgorithm.from_jwk`. Supabase
   Auth signs with **ES256 (P-256)** — so even once the JWKS is wired, a real
   Supabase token will not verify until the verifier learns ES256.

The three settings `SUPABASE_JWT_ISSUER`, `SUPABASE_JWT_AUDIENCE` and
`SUPABASE_JWKS_URL` (now in `.env.example`) are read by `settings.py` at
request time, but they appear nowhere else in the repo — the wiring that
consumes them is the missing piece.

**What this means for a developer today:** the read-only half of the app
(`/health`) runs, but no authenticated or database-backed route works. Getting a
real Supabase token — from `https://<project-ref>.supabase.co/auth/v1`, with the
JWKS at `…/.well-known/jwks.json`, then attaching it as `VITE_DEV_TOKEN` — is a
separate bite together with the two fixes above. This is reported, not absorbed:
see the PR body for the full finding.

---

## 7. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
```

`frontend/.env.example` has three keys. For now only `VITE_DEV_TOKEN` matters
(the dev auth shim reads it, or `localStorage["fcp.devToken"]`); leave
`VITE_API_PROXY_TARGET=http://localhost:8000` as the default. A real token
cannot be supplied until §6 is resolved — without one, the SPA still serves but
every authenticated call fails with 401/500.

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

**`GET /api/v1/me` returns 500, not 401, with a valid-looking token.**
Cause: no keyset/session wiring (§6) — `jwks_keyset` is `None`. A missing
`SUPABASE_JWT_ISSUER` also surfaces here as an unhandled `SettingsError`
(500). Fix: none in the runbook; this is the §6 finding.

**`alembic upgrade head` says `required setting DATABASE_URL is not set`.**
Cause: `DATABASE_URL` is not exported in the shell running alembic. Fix:
`export DATABASE_URL=…` first (the URL is never in `alembic.ini`).

**`docker compose up -d db` fails to bind `:5432`.**
Cause: another Postgres already owns the port. Fix: stop it, or run the compose
service on a different host port and point `DATABASE_URL` at it.

**`uvicorn` errors with `no module named backend` when run from outside the repo root.**
Cause: the editable install is per-venv; run `uvicorn` from the repo root with
the venv active.
