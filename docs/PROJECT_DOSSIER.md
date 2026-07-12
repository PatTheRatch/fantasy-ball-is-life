# Project Dossier

An inventory of everything built so far, and a clear definition of what this
thing should be. This is the north-star doc — when a decision needs grounding,
it grounds here.

> A designed, visual version of this dossier exists as a Claude artifact:
> https://claude.ai/code/artifact/ee115ab9-685f-4ad7-bb28-1b32787a048d
> This Markdown file is the canonical, version-controlled source of truth.

**Snapshot:** 2 origin codebases (v1 + v2) · 27 backend endpoints · 4 frontend
pages (3 built) · ~7k lines of Python analytics.

---

## 00 · The reframe

"Start fresh" means fresh **structure**, not a rewrite. The analytics engine —
draft optimizer, every-team-vs-every-team win math, playoff simulator, AI
recaps — is hard-won IP that already works. Throwing it out means re-deriving
months of basketball logic.

What actually needed to be new: a single repo with a clean layout, league config
lifted out of the source, and a sharp product focus. The **PatriotGames (v2)**
folder was already ~70% of that skeleton, so we consolidated into it rather than
starting from zero. **(Done — see §05.)**

---

## 01 · The asset register

Everything of value came from two folders, neither previously under version
control. Both now archived read-only; the consolidated code lives in this repo.

### The Engine — `fantasy_bball` (v1, the analytics)

| Asset | What it does | Disposition |
|---|---|---|
| ESPN data pull (`data_feed.py`) | Pulls rosters, transactions, matchups, scoreboards; fuzzy-matches projections; builds storyline metrics | **Keep · core** |
| Draft optimizer (`optimize_lineup.py`) | Integer-program auction drafting under budget/position/category constraints; generates 20 varied plans | **Keep · flagship** |
| League math (`fantasy.py — MyLeague`) | Power rankings + "universe wins" (every team vs every other team). Has a real perf bug to fix | **Keep · refactor** |
| Playoff simulator (`season_simulation.py`) | 40k-run Monte Carlo of final seeds — the clinch graphics posted to the group chat | **Keep** |
| Draft Monte Carlo + targets (`monte_carlo_targets.py`, `utils.py`) | Simulates thousands of drafts to derive category targets; 75%-win constraint math | **Keep · fold in** |
| Punt-strategy analysis (`get_correlations.py`) | Category correlation study for choosing punts | **Keep as notebook** |
| Historical league data (~120 CSV/XLS) | Every weekly scoreboard, roster, transaction log — a real backtesting dataset | **Archive** |
| Flask draft UI (`app.py`, `templates/`) | Early optimizer web UI, superseded by v2 React app | **Retire** |
| Stray files (`venv/`, `Roblox.dmg`, dup configs) | 1.1 GB venv committed with code; Roblox installer; `ProjectionConfig` defined twice | **Delete** |

### The Product Shell — `PatriotGames` (v2, where work left off)

| Asset | What it does | Disposition |
|---|---|---|
| FastAPI backend (`api.py`, 27 endpoints) | League meta, standings, power rankings, matchup win-probability, rosters, transactions, scoreboards, projections upload, optimizer | **Keep · backbone** |
| AI commentary (`/matchup-commentary`, `/league-recap`, `/season-commentary`) | Calls Claude to write recaps directly — already replaces the ChatGPT copy-paste workflow. Uses a deprecated model in 3 spots | **Keep · update model** |
| React web app (`frontend/`, React 19 + Vite + Tailwind) | In-Season, Recap, Season pages built; API client fully wired; Draft page is a 26-line stub | **Keep · finish** |
| Streamlit dashboard (`app.py`, 4 tabs) | Draft Optimizer / In-Season / Weekly Recap / Season — the working internal tool | **Keep as internal** |
| Config + docs (`config.py`, `requirements.txt`, `ESPN_ACCESS_HANDOFF.md`) | Env-var credentials; the handoff doc written to seed exactly this project | **Keep** |

---

## 02 · The product

**A GM's cockpit for 9-category head-to-head fantasy basketball.** Not another
stats site — it closes the loop from *data* to *decision* to *story* (the three
things a manager actually does each week) and automates the tedious parts.

**Who it's for:** serious 9-cat H2H managers — the people who already pay for
projections and run their leagues on group chats. Power users first; they forgive
rough edges and tell you what's missing.

**The core loop it automates:**

1. **Connect** — link your ESPN league once; rosters/matchups/transactions pull automatically.
2. **Decide** — category win-probability, streaming suggestions, and the draft optimizer tell you who to start/add/target.
3. **Recap** — AI writes the weekly recap in your league's voice.
4. **Deliver** — recap posts itself to the group chat on schedule; the loop runs without you.

Step 4 — **self-delivering recaps** — is the demo that sells this, and the itch
that started the whole project.

---

## 03 · The build order

Scope the product v1 to five features that make the core loop real end-to-end for
Patrick's league. Everything else waits until that works and someone else is using it.

### Starting Five — ship this (order re-ranked 2026-07-12, see Decision D)

| Rank | Slot | Feature | State |
|---|---|---|---|
| 1 | PF | Draft optimizer in the app | **Shipped** — full Draft Room (PRs #2–#11): diverse plan portfolio, per-pick recompute, triage/relax, MC category targets, custom saved plans, Forge Value pricing. Feature-paused; Patrick drafts with it first |
| 2 | SF | Auto weekly recap → group chat | **Next feature** (needed by season week 1). AI endpoint exists; scheduling + delivery not started |
| 3 | PG | League connect + auto-pull | Mostly built; no caching, 2 open correctness findings in the audit |
| 4 | SG | In-season matchup dashboard (live category win-probability) | Built in React |
| 5 | C | Season / playoff odds | Season page built; ⚠️ the v1 playoff simulator (`season_simulation.py`) was marked "Keep" in §01 but never actually copied into this repo — recover from the archive or re-scope |

### The Bench — later

Multi-league & multi-user accounts · Yahoo/Sleeper support · our own projection
model · streaming/add-drop optimizer · mobile wrapper & monetization.

### The Cut List — don't carry forward

The 1.1 GB of committed junk · two drifting copies of every file · hardcoded
season logic (hand-typed week calendar and current-week number — derive from ESPN).

---

## 04 · Decisions (locked 2026-07-08, by Patrick as product owner)

**A — Audience.** Build for Patrick + his league first. Do it right and a wider
mid-season launch is on the table. Keep the architecture multi-league-ready so
that launch is a config flip, not a rewrite.

**B — Projections.** User uploads now, behind a pluggable projection-source
framework: one normalized schema; Basketball Monster, ESPN, Hashtag Basketball,
and eventually our own model each plug in as an adapter. Full design:
[`docs/specs/PROJECTION_SOURCE_FRAMEWORK.md`](specs/PROJECTION_SOURCE_FRAMEWORK.md).

**C — Platform.** Web-first. Ship to the league as a web app, prove the loop,
wrap for mobile only if there's real pull.

**D — Build order re-ranked (2026-07-12).** The Draft Room is deliberately the
#1 priority, not a drift: the draft happens before the season starts, so it's
the first moment this app gets used for real. Rollout is **Patrick-first** —
he drafts with it privately (a competitive edge is the point), verifies it
works under live conditions, and only then ships it to the league. §02's
"self-delivering recaps is the demo that sells this" framing stays true for
the *league-facing* launch — the recap loop is what the group actually sees —
so **weekly recap automation is the #2 priority and the next feature**, needed
by week 1 of the season. The Draft Room is feature-paused at its current state
(good enough to draft with); before recap work starts, the codebase gets the
long-deferred cleanup + backend restructure so the next feature lands on a
clean foundation.

---

## 05 · Progress (refreshed 2026-07-12)

- [x] Repo created and everything put under version control.
- [x] PatriotGames code consolidated into this repo behind a `.gitignore`
      (secrets, venvs, node_modules, and all local data files excluded).
- [x] Operating manual and roles documented (`docs/AISHA_OPERATING_MANUAL.md`).
- [x] Projection-source framework spec written; open questions resolved;
      pending Aisha's technical review.
- [x] Review-gated contribution workflow documented (`CONTRIBUTING.md`);
      branch protection still to be enabled on `main` (Patrick, repo settings).
- [x] ESPN integration audited; the category-target week-sampling bug it found
      is fixed. Remaining findings (2 correctness, several reliability) tracked
      in [`docs/ESPN_INTEGRATION_AUDIT.md`](ESPN_INTEGRATION_AUDIT.md).
- [x] **Draft Room shipped end to end** (PRs #2–#11): spec + Aisha's review,
      plan-diversity engine, `/draft/*` API, full React DraftPage, optimization
      controls (categories/percentile/objective, exclude/favorite/target
      players), Monte Carlo category targets (Patrick's port), solver time
      bounding, custom saved plans, selectable pricing source (Forge Value),
      auction-value simulator. 106 tests passing.
- [x] **Cleanup pass (2026-07-12):** dead code removal, duplicate
      `ProjectionConfig`, hardcoded league-personal data out of engine code,
      `games_per_week` drift, deprecated Claude model IDs, CI workflow (PR #12).
- [x] Restructure the flat backend into a `backend/` package — spec approved
      by Aisha (2026-07-12), answers MC spec open question #1. PR 1 (move +
      rename) done; PR 2 (split `backend/api/main.py` into routers +
      `commentary/`) still open.
- [ ] **Close the loop: schedule + deliver weekly recaps to the group chat —
      the next feature** (Decision D). Needed by season week 1.
- [ ] Implement the projection-source framework (after Aisha's review).
- [ ] Recover or re-scope the v1 playoff simulator (see Starting Five, C slot).

---

*Project: fantasy-ball-is-life · League: Patriot Games (ESPN, H2H 9-cat) ·
Status: Draft Room shipped & paused · cleanup pass under way · next feature:
automated weekly recaps.*
