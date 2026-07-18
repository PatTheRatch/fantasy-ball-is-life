# fantasy-ball-is-life

A GM's cockpit for 9-category head-to-head fantasy basketball. Connects to your
ESPN league, tells you who to start/add/target, and writes the weekly recap for
your league group chat automatically.

## Status

Consolidated from the working `PatriotGames` codebase (July 2026). Currently a
single-league app for the Patriot Games league; architecture is being made
multi-league-ready for a possible wider mid-season launch.

Product decisions (locked 2026-07-08):

- **Audience:** Patrick's league first; wider launch later if it earns it.
- **Projections:** user-uploaded for now, behind a pluggable projection-source
  framework (Basketball Monster / ESPN / Hashtag Basketball / our own model) —
  see `docs/specs/PROJECTION_SOURCE_FRAMEWORK.md`.
- **Platform:** web-first. No App Store until the auth story is solid.

Team roles and the feature definition-of-done live in
[`docs/AISHA_OPERATING_MANUAL.md`](docs/AISHA_OPERATING_MANUAL.md).

## Layout

Backend lives under `backend/`, grouped by concern
(`docs/specs/BACKEND_RESTRUCTURE.md`, approved by Aisha 2026-07-12):

| Path | What |
|---|---|
| `backend/api/main.py` | FastAPI app factory; routers under `backend/api/routers/` (league, draft, commentary, projections, optimizer); shared helpers in `backend/api/deps.py` |
| `backend/commentary/` | AI commentary: prompt builders, provider clients, and validated structured recap generation |
| `backend/league/` | `data_feed.py` (ESPN pull layer — rosters, transactions, matchups, scoreboards, projection attachment); `fantasy.py` (`MyLeague` — power rankings, universe-wins math) |
| `backend/draft/` | The Draft Room engine: `optimizer.py` (auction draft optimizer, cvxpy integer program), `engine.py` (per-pick recompute loop), `strategies.py` (plan-diversity strategy map), `targets_mc.py` (Monte Carlo category targets), `values.py` (Forge Value — projection-derived auction values), `auction_sim.py` (auction-room price simulator) |
| `backend/analytics/consistency.py` | Player consistency metrics (feeds the confidence endpoints) |
| `backend/config.py` | Central config — ESPN credentials, league-owner draft-pool knobs, tunable constants |
| `backend/projections/` | Reserved for the projection-source framework (`docs/specs/PROJECTION_SOURCE_FRAMEWORK.md`, pending review); empty for now |
| `frontend/` | React 19 + Vite + Tailwind web app (the product UI) |
| `docs/` | Operating manual, project dossier, ESPN access handoff, feature specs |
| `player_rankings/`, `data/` | Local data drop zones — gitignored |

## Setup

```bash
# Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys/cookies (see docs/ESPN_ACCESS_HANDOFF.md)
uvicorn backend.api.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

Phase 1 weekly recap drafts default to DeepSeek's lower-cost
`deepseek-v4-flash` model. Set `DEEPSEEK_API_KEY` and
`RECAP_LLM_PROVIDER=deepseek` in the root `.env`; the key stays server-side.
The legacy commentary endpoints continue to use `ANTHROPIC_API_KEY`.

## The 9 categories

`PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO` — turnovers score inverted (lower is better).
