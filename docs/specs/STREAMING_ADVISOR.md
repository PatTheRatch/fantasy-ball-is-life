# Feature Spec: Streaming Advisor — automated add/drop suggestions

**Status:** Product direction set by Patrick (owner) 2026-07-24 — pending
Aisha's technical review before implementation (per
`docs/AISHA_OPERATING_MANUAL.md`).
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-24
**Decision basis:** The site already *reports* (recaps, standings, live
matchups) and advises at *draft time* (MC draft targets, auction optimizer).
This is the first **in-season advising** feature: given the live matchup and
its forecast, suggest concrete waiver adds (and who to drop) that flip
losable categories.

---

## 1. User story

> I'm down 4 in steals, and the forecast says I'm going to *lose* steals.
> Tell me who's available on waivers with games left this week who gets
> steals — and who on my roster I can afford to drop for them.

The one-sentence product: **"You're losing STL and BLK. Add X (3 games left,
1.8 spg), drop Y (1 game left, doesn't move your winnable categories)."**

## 2. What already exists (build on it, don't rebuild it)

This feature is mostly *composition* of machinery the codebase already has:

| Need | Already exists |
|---|---|
| Live category score ("down 4 in steals") | `scoreboard` phase / `get_current_scoreboard` — per-category home/away tallies |
| Forecast ("projected to lose steals") | `feed.get_projected_scoreboard()` + `GET /leagues/{slug}/matchup-confidence` (per-category projected totals + confidence tiers) |
| Available players | `espn_api` `League.free_agents(week, size, position)` — the league's actual FA/waiver pool |
| Games remaining this week | `get_pro_schedule()` + the `num_games_left` per-player pipeline already used by `rosters/current` |
| Per-game player projections | The pluggable projection framework (`backend/projections/` — ESPN last-15/30, BBM, Hashtag adapters → one canonical `PlayerProjection` schema) |
| Injury status | Already surfaced in the roster pipeline (`injuryStatus`, zero-out-no-games logic) |
| 9-cat category math (incl. TO negative, FG%/FT% ratios) | Draft optimizer / auction values / `canonical_matchups` tally logic |
| AI narrative (optional last step) | Commentary infra (`backend/commentary/`) |

The genuinely new pieces: the **gap analysis** (classifying categories),
**free-agent valuation** (expected remaining-week contribution), and the
**pairing engine** (which add+drop nets the most category flips).

## 3. The pipeline

Per team, per current matchup week — computed on demand:

### 3.1 Category gap analysis
For each of the 9 categories, combine the **live** tally and the **projected**
final:

| Classification | Meaning |
|---|---|
| `safe_win` | winning now, projected to win comfortably |
| `narrow_win` | winning, projected margin small — *protect this* |
| `toss_up` | projected margin within noise |
| `winnable_deficit` | losing now, projected loss is small — **target** |
| `lost_cause` | losing big, projection agrees — don't chase |

"Down 4 in steals *and* forecasted to lose steals" lands in
`winnable_deficit` (or `lost_cause` if the projected gap is hopeless — the
advisor should explicitly *not* chase those; punting is correct strategy).
Margins are normalized per category (a 4-steal gap ≠ a 4-point gap): divide
by the projection's per-category weekly stddev across teams (cheap to compute
from the projected scoreboard) so "small" means the same thing in every
category. Ratio categories (FG%, FT%) use projected made/attempts, not the
percentage directly.

### 3.2 Candidate pool
`league.free_agents(size=~150)` → filter: not injured-out, has ≥1 game
remaining in the week window. Flag (don't hide) waiver-locked players. The
pool call needs the league's ESPN credentials — same `connect()` path the
worker uses.

### 3.3 Valuation
For every candidate **and** every current-roster player, expected
remaining-week contribution per category:

```
expected[cat] = per_game_projection[cat] × games_remaining_this_week
```

Per-game projections come from the **projection framework's active source**
(default: ESPN last-15), so a league that uploads BBM projections gets
BBM-driven advice for free — the advisor never touches source-specific
columns (framework acceptance criterion 2). Games-remaining from the pro
schedule; injured players zeroed as in the existing roster pipeline.

### 3.4 Pairing engine (the suggestion)
Score every (add, drop) pair by **net expected category flips**:

1. Apply the swap to my team's projected category totals
   (`- drop.expected + add.expected`, ratio cats recomputed via made/attempts).
2. Recount projected category wins vs the opponent.
3. `score = (flips L→W in winnable_deficit/toss_up) − (flips W→L anywhere)`,
   tie-broken by total projected-margin improvement in targeted categories.

Guardrails:
- **The Wemby rule — long-term value beats this-week schedule.** A naive
  week-scoped engine would happily conclude "star big, 1 game left this week,
  weak in your target category → droppable for a 4-game streamer." That is
  catastrophic advice: you never drop Wembanyama in week 2 because you need
  assists. Drop candidacy is therefore gated on **surplus over replacement**,
  computed on the *season* horizon, before any this-week math runs:

  ```
  replacement_value   = best available FA's season per-game value
  surplus(player)     = player_season_value − replacement_value
  droppable(player)   ⇔ surplus(player) ≤ DROP_THRESHOLD
  ```

  Season per-game value comes from the projection framework's **season
  horizon** (it already distinguishes season vs weekly exports) via the same
  9-cat z-score/value math the draft optimizer uses (`value_col`). A star's
  surplus over any FA is enormous, so he is *never* in the drop pool — no
  matter how thin his week looks. Fringe players sit at/below replacement and
  churn freely. This gate runs **first**; the weekly pairing engine (above)
  only ever sees the droppable tail of the roster. Suggestions display each
  drop's surplus so the trade-off is visible ("costs ~0 long-term value").
- Never suggest dropping a player whose removal flips a `narrow_win` to a
  loss (the "don't drop your steals anchor to chase blocks" rule falls out of
  the math, but assert it explicitly in tests).
- Skip `lost_cause` categories when scoring gains (no wasted moves).
- Respect ESPN acquisition limits if the league sets them (surface "X/Y adds
  used" but don't hard-block — the user decides).
- Deterministic: same inputs → same suggestions, fully unit-testable. **No
  LLM in the scoring path** (an optional narrative layer comes later, S-6).

Output: top ~3 pairs, each with the full why: targeted categories,
games-left, per-category expected deltas, and what the swap does to the
projected matchup line (e.g. "4–5 → 6–3").

### 3.5 API + UI
- `GET /leagues/{slug}/advisor/suggestions?team=<team_name>&week=<w>` —
  computed on demand, cached ~15 min (aligns with the refresh cadence; the
  inputs only move that fast). Public-read like the other league endpoints;
  the team param means anyone can view any team's suggestions — fine for v1
  (it's all derived from data the league can already see).
- UI: a **"Suggested moves"** card on the Matchup page's Tools tab
  (`ScoreboardTools`), auto-loading (D-P6), shown for the viewer's claimed
  team by default with a team switcher. Each suggestion renders the
  category-flip line + expected deltas; no action buttons in v1 (we can't
  execute ESPN transactions — link out to ESPN).

## 4. Where `nba_api` fits — deliberately *not* the critical path

v1 ships entirely on data we already have (ESPN averages + pro schedule).
`nba_api` (new dependency, unofficial NBA stats endpoints, rate-limited,
occasionally flaky) enters later as **an enrichment adapter inside the
projection framework** — exactly the "new source = one adapter + tests"
seam that framework was built to prove:

- **Recent-form signal:** last-N-games splits with minutes trends (who just
  entered a starting lineup — the core streaming signal ESPN averages lag on).
- **Schedule context:** opponent pace/defensive rating to weight expected
  production.

Positioning it as an adapter means the advisor's valuation code never knows
nba_api exists — it just sees `PlayerProjection` rows from whatever source is
active. If nba_api breaks (it periodically does), the advisor degrades to
ESPN data instead of breaking.

## 5. Synergy with daily snapshots (`DAILY_SNAPSHOTS.md`)

The daily roster snapshots make the advisor *accountable*: since we'll know
each team's roster every day, we can later evaluate "did the user take the
suggested add, and did it win them the category?" — a retrospective
("Advisor report card") that's impossible without roster history. v1 logs
each served suggestion set to a small `advisor_suggestions` table
(league/team/week/date + payload) so that evaluation is possible later.

## 6. Data model

One optional table (the pipeline itself is stateless/on-demand):

### `advisor_suggestions`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `league_id` | uuid fk → leagues | |
| `season` / `week` | int | |
| `team_name` | text | whose suggestions |
| `served_on` | date | |
| `payload_json` | jsonb | the full suggestion set as served |
| `created_at` | timestamptz | |
| | | unique (league_id, season, week, team_name, served_on) — one logged set per team per day |

Service-role write, public-league RLS read (same pattern as the snapshot
tables).

## 7. Phases

| Phase | Scope | Depends on | Done when |
|---|---|---|---|
| **S-1** | Category gap analysis: `backend/advisor/gaps.py` — live + projected scoreboard → per-category classification (normalized margins, ratio-cat handling) | — | Unit tests: each classification reachable; ratio cats via made/attempts; deterministic |
| **S-2** | Valuation, both horizons: FA pool + games-remaining + active projection source → expected remaining-week contribution per category (roster players too), **plus season-horizon per-game value and surplus-over-replacement per roster player** | S-1 | Hermetic tests (mock `free_agents`/schedule/projections); injured-out and zero-games filtered; waiver-locked flagged; surplus computed from the season horizon |
| **S-3** | Droppability gate + pairing engine + `GET /leagues/{slug}/advisor/suggestions` (+ `advisor_suggestions` logging, 15-min cache) | S-2 | Guardrail tests: **the Wemby test** (high-surplus star never suggested as a drop, even with 1 game left and a deficit in his weak category); never breaks a `narrow_win`; skips `lost_cause`; top-3 deterministic; endpoint contract tests |
| **S-4** | UI: "Suggested moves" card on Matchup Tools tab (auto-load, claimed-team default, team switcher) | S-3 | Vitest: renders suggestions + category-flip line; empty/error states; slug-scoped query keys |
| **S-5** *(later)* | `nba_api` enrichment adapter in the projection framework (recent form + minutes trends), behind the standard adapter interface | S-3 | Adapter + tests only, zero advisor changes (framework criterion 6) |
| **S-6** *(later)* | AI narrative on suggestions ("why this move") via commentary infra | S-3 | Narrative renders under each suggestion; deterministic math unchanged |

S-1→S-4 is the shipping path. Each phase is a separate PR, sized to the
one-slice-at-a-time delivery model used for N-4.

## 8. Test plan

- **S-1:** golden-case unit tests per classification; normalization sanity
  (a 4-steal gap classifies differently than a 4-point gap); FG%/FT% via
  made/attempts; TO inverted.
- **S-2/S-3:** fully hermetic — mock the ESPN pool, schedule, and projection
  source. Property-style guardrails: no suggestion may reduce projected
  category wins; suggestions stable under input reordering. **The Wemby
  test:** construct a roster with a top-5 season-value player who has 1 game
  left and is weak in the team's `winnable_deficit` category, plus a fat
  4-game FA streamer — assert the star is never the suggested drop and the
  actual suggestion comes from the sub-replacement tail.
- **Endpoint:** contract tests (shape, cache header, unknown team → 404,
  team with no claimed games → empty suggestions, not an error).
- **Meta:** clean-env runs (`env -u …`) and real-signature (`spec=`) mocks —
  the standing lessons from the N-4 batch.

## 9. Risks & open questions

- **Compute cost per request:** FA pool (~150 players) × valuation is a few
  ESPN calls + arithmetic — fine on demand with the 15-min cache. If it grows,
  precompute for claimed teams in the refresh worker.
- **Projection quality is the ceiling.** ESPN last-15 lags breakouts —
  that's the S-5 nba_api case, deliberately deferred, not blocking.
- **ESPN ToS/fragility:** `free_agents` is one more read on the existing
  authed session; unchanged risk profile.
- **Ratio-category math is the classic bug farm** (FG% adds affect the
  denominator). Reuse the made/attempts machinery from the projected
  scoreboard; test it hard.
- **Open:** default FA pool size (150?) and whether to let the user
  position-filter in the UI (v1: no filter, show top pairs).
- **Open:** `DROP_THRESHOLD` tuning — how much surplus over replacement makes
  a player "core" vs "streamable." Start conservative (protect more than
  strictly optimal; a too-timid advisor is annoying, a Wemby-dropper is dead
  on arrival) and tune against real rosters. Consider expressing it as a
  roster percentile ("bottom ~3 slots are streamable") rather than an
  absolute value number.
- **Open:** should suggestions consider *multi-add* strategies (2 moves)?
  v1: single add/drop pairs only — multi-move is combinatorial and rarely
  actionable before waivers clear.

## 10. Out of scope (v1)

- Executing transactions on ESPN (we advise; the user acts on ESPN).
- Waiver claim priority modeling / FAAB bid advice.
- Multi-week planning ("stream for next week's schedule") — v1 is
  this-week-only.
- Punt-strategy configuration ("I always punt FT%") — the `lost_cause`
  classification approximates it; explicit punt settings later.
- The nba_api adapter (S-5) and AI narrative (S-6) — specced, not v1.
- Advisor report card (needs daily-snapshot history to accrue first).
